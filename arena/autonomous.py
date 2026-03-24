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
from typing import Optional

import httpx

from .clients import FerriculaClient, ChonkClient, parse_status
from .tools import web_search, fetch_page


# How often the autonomous loop ticks (seconds)
THINK_INTERVAL = 45
# Chance of initiating a thought per tick (0-1)
THOUGHT_PROBABILITY = 0.35
# Chance of web searching per tick
SEARCH_PROBABILITY = 0.15


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
    last_dream_check = 0
    last_thought = time.time()
    thought_count = 0

    while not stop_event.is_set():
        try:
            await asyncio.sleep(THINK_INTERVAL)
        except asyncio.CancelledError:
            return

        if stop_event.is_set():
            return

        now = time.time()

        # ── Check if a dream happened recently ──
        try:
            clock_resp = await ferricula._get("clock")
            clock_data = json.loads(clock_resp)
            clock_text = clock_data.get("result", "")
            # Parse dream count
            import re
            dream_match = re.search(r"dreams=(\d+)", clock_text)
            current_dreams = int(dream_match.group(1)) if dream_match else 0

            if current_dreams > last_dream_check and last_dream_check > 0:
                # A dream happened! Reflect on it.
                interrupt_callback(
                    f"\n  [{name} stirs — a dream just passed. "
                    f"{current_dreams} total dreams.]\n"
                )
                # Small chance of sharing what the dream surfaced
                if random.random() < 0.5:
                    await _dream_reflection(
                        ferricula, chonk, name, api_key, model,
                        identity, interrupt_callback,
                    )
            last_dream_check = current_dreams
        except Exception:
            pass

        # ── Random thought — recall a memory and react ──
        if random.random() < THOUGHT_PROBABILITY:
            await _spontaneous_thought(
                ferricula, chonk, name, api_key, model,
                identity, interrupt_callback,
            )
            thought_count += 1

        # ── Random web search — curiosity-driven ──
        elif random.random() < SEARCH_PROBABILITY and api_key:
            await _curiosity_search(
                ferricula, chonk, name, api_key, model,
                identity, interrupt_callback,
            )


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
    """After a dream, reflect on what changed."""
    try:
        # Get current status to see what the dream did
        status = await ferricula.status()

        system = (
            f"You are {name}'s post-dream awareness. A dream just completed. "
            f"You have {status.active} active memories, {status.keystones} keystones, "
            f"{status.graph_edges} edges. "
            f"Share one brief observation about what you're noticing. "
            f"One sentence. Like waking up and having a thought."
        )

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": model,
                    "max_tokens": 80,
                    "system": system,
                    "messages": [{"role": "user", "content": "What did the dream leave you with?"}],
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
        callback(f"\n  [{name} waking] {thought}\n")

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
