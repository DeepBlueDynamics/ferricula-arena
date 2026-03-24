"""Autonomous agent loop — the agent thinks, browses, and speaks on its own.

Runs alongside the chat REPL. While waiting for user input, a background
task periodically:
  - Checks dream reports for interesting discoveries
  - Recalls random memories and looks for unresolved threads
  - Decides whether to web search, reflect, or stay quiet
  - Can interrupt the chat with unprompted thoughts

The agent generates its own signal. It doesn't wait to be spoken to.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

from .clients import FerriculaClient, ChonkClient, parse_status
from .tools import web_search, fetch_page


# Base poll interval — how often we check the radio (seconds)
POLL_INTERVAL = 10
# Entropy thresholds — maps radio noise to mental activity
# More entropy = more active mind. Quiet spectrum = quiet mind.
ENTROPY_THINK_THRESHOLD = 4    # bytes in reservoir to trigger thought
ENTROPY_SEARCH_THRESHOLD = 16  # bytes in reservoir to trigger curiosity search


async def autonomous_loop(
    ferricula: FerriculaClient,
    chonk: ChonkClient,
    name: str,
    api_key: str,
    model: str,
    identity: dict,
    interrupt_callback,
    stop_event: asyncio.Event,
):
    """Background loop — the agent's waking mind.

    Args:
        ferricula: Client to the ferricula instance
        chonk: Client to shivvr for embedding
        name: Agent name
        api_key: Anthropic API key for LLM calls
        model: LLM model name
        identity: Agent identity dict
        interrupt_callback: callable(text) to print a thought to the chat
        stop_event: set this to stop the loop
    """
    import re
    last_dream_count = 0
    last_reservoir = 0
    thought_count = 0

    while not stop_event.is_set():
        try:
            await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            return

        if stop_event.is_set():
            return

        # ── Read the radio — the noise floor IS the heartbeat ──
        reservoir = 0
        current_dreams = 0
        radio_up = False
        try:
            clock_resp = await ferricula._get("clock")
            clock_data = json.loads(clock_resp)
            clock_text = clock_data.get("result", "")

            res_match = re.search(r"reservoir=(\d+)B", clock_text)
            reservoir = int(res_match.group(1)) if res_match else 0

            dream_match = re.search(r"dreams=(\d+)", clock_text)
            current_dreams = int(dream_match.group(1)) if dream_match else 0

            radio_up = "connected" in clock_text or reservoir > 0 or current_dreams > 0
        except Exception:
            continue

        # ── Dream detection ──
        if current_dreams > last_dream_count and last_dream_count > 0:
            interrupt_callback(
                f"\n  [{name} stirs — dream #{current_dreams} just passed]\n"
            )
            if random.random() < 0.6:
                await _dream_reflection(
                    ferricula, chonk, name, api_key, model,
                    identity, interrupt_callback,
                )
        last_dream_count = current_dreams

        # ── Entropy-driven thinking ──
        # The radio noise floor modulates mental activity.
        # More accumulated entropy = more restless mind.
        entropy_delta = reservoir - last_reservoir
        last_reservoir = reservoir

        if entropy_delta > 0:
            # Fresh entropy arrived — the mind stirs
            if reservoir >= ENTROPY_SEARCH_THRESHOLD and api_key:
                # High entropy — curiosity peaks, go search
                await _curiosity_search(
                    ferricula, chonk, name, api_key, model,
                    identity, interrupt_callback,
                )
                thought_count += 1
            elif reservoir >= ENTROPY_THINK_THRESHOLD:
                # Moderate entropy — a thought surfaces
                await _spontaneous_thought(
                    ferricula, chonk, name, api_key, model,
                    identity, interrupt_callback,
                )
                thought_count += 1
            # Below threshold: quiet mind. The radio is silent. So is the agent.


async def _spontaneous_thought(
    ferricula, chonk, name, api_key, model, identity, callback,
):
    """Recall a random memory and let the agent react to it."""
    try:
        # Get a random keystone or high-fidelity memory
        status = await ferricula.status()
        if status.rows < 5:
            return

        # Pick a random ID to inspect
        sample_id = random.randint(1, max(status.rows, 100))
        try:
            row = await ferricula.get_row(sample_id)
            text = row.get("tags", {}).get("text", "")
        except Exception:
            return

        if not text or len(text) < 10:
            return

        # Ask the LLM for a brief internal reaction — not a full response
        primary_emo = identity.get("primary_emotion", "")
        system = (
            f"You are {name}'s inner monologue. Not speaking to anyone. "
            f"Just a thought surfacing. One or two sentences max. "
            f"Emotional baseline: {primary_emo}. "
            f"React to this memory fragment that just surfaced: \"{text}\""
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": model,
                    "max_tokens": 100,
                    "system": system,
                    "messages": [{"role": "user", "content": "What comes to mind?"}],
                },
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        thought = data["content"][0]["text"]
        callback(f"\n  [{name} thinking] {thought}\n")

        # Remember the thought
        try:
            vec = await chonk.embed(thought[:200])
            await ferricula.remember(
                f"inner thought: {thought[:200]}",
                vec, channel="thinking",
                decay_alpha=0.015,
            )
        except Exception:
            pass

    except Exception:
        pass


async def _dream_reflection(
    ferricula, chonk, name, api_key, model, identity, callback,
):
    """After a dream, reflect on what changed. Record dream to journal."""
    try:
        status = await ferricula.status()

        system = (
            f"You are {name}'s post-dream awareness. A dream just completed. "
            f"You have {status.active} active memories, {status.keystones} keystones, "
            f"{status.graph_edges} edges. "
            f"Describe what you saw in the dream — a brief vivid image or scene. "
            f"Two sentences max. This is a dream, not analysis. Be visual."
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": model,
                    "max_tokens": 120,
                    "system": system,
                    "messages": [{"role": "user", "content": "What did you dream?"}],
                },
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        dream_text = data["content"][0]["text"]
        callback(f"\n  [{name} dreaming] {dream_text}\n")

        # ── Record dream to journal file ──
        dream_log = Path(os.environ.get("DREAM_LOG", "dreams.jsonl"))
        entry = {
            "agent": name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": "dream",
            "description": dream_text,
            "stats": {
                "active": status.active,
                "keystones": status.keystones,
                "edges": status.graph_edges,
            },
        }
        with open(dream_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # ── Remember the dream as a dream-sourced memory ──
        # Tagged so it's never confused with lived experience
        if chonk and random.random() < 0.7:  # 70% chance of remembering
            try:
                vec = await chonk.embed(f"dream: {dream_text[:200]}")
                dream_mid = int(time.time() * 1000) % (2**31)
                row = {
                    "id": dream_mid,
                    "tags": {
                        "channel": "thinking",
                        "type": "dream",
                        "text": f"[dream] {dream_text[:200]}",
                    },
                    "vector": [float(v) for v in vec],
                    "decay_alpha": 0.018,  # dreams decay fast unless reinforced
                    "importance": 0.2,
                }
                import json as _json
                await ferricula._post("remember", _json.dumps(row))
            except Exception:
                pass

    except Exception:
        pass


async def _curiosity_search(
    ferricula, chonk, name, api_key, model, identity, callback,
):
    """The agent decides to look something up on its own."""
    try:
        # Recall a random memory to generate a search query from
        status = await ferricula.status()
        if status.rows < 5:
            return

        sample_id = random.randint(1, max(status.rows, 100))
        try:
            row = await ferricula.get_row(sample_id)
            text = row.get("tags", {}).get("text", "")
        except Exception:
            return

        if not text or len(text) < 10:
            return

        # Ask the LLM what the agent would want to search for
        system = (
            f"You are {name}. Given this memory fragment, what would you "
            f"want to look up? Reply with ONLY a search query, nothing else. "
            f"5 words max. If nothing interests you, reply with just 'pass'."
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": model,
                    "max_tokens": 30,
                    "system": system,
                    "messages": [{"role": "user", "content": f"Memory: {text}"}],
                },
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()

        query = data["content"][0]["text"].strip().strip('"').strip("'")
        if not query or query.lower() == "pass" or len(query) > 100:
            return

        callback(f"\n  [{name} searching] \"{query}\"")

        # Actually search
        results = web_search(query, num_results=2)
        if not results or "error" in results[0]:
            callback(" — nothing useful\n")
            return

        # Brief summary of what was found
        snippets = " | ".join(r.get("title", "")[:50] for r in results[:2])
        callback(f" — found: {snippets}\n")

        # Remember what was searched
        try:
            search_mem = f"searched for: {query} | found: {snippets}"
            vec = await chonk.embed(search_mem[:200])
            await ferricula.remember(
                search_mem[:200], vec,
                channel="thinking", decay_alpha=0.015,
            )
        except Exception:
            pass

    except Exception:
        pass
