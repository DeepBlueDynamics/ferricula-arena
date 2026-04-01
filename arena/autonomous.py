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

from .clients import FerriculaClient, ShivvrClient, parse_status
from .tools import web_search, fetch_page


# Base poll interval — how often we check the radio (seconds)
POLL_INTERVAL = 10
# Entropy thresholds — maps radio noise to mental activity
# More entropy = more active mind. Quiet spectrum = quiet mind.
ENTROPY_THINK_THRESHOLD = 4    # bytes in reservoir to trigger thought
ENTROPY_SEARCH_THRESHOLD = 16  # bytes in reservoir to trigger curiosity search


async def autonomous_loop(
    ferricula: FerriculaClient,
    shivvr: ShivvrClient,
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
        shivvr: Client to shivvr for embedding
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
            # Body sense — interoception after dream
            await _body_sense(ferricula, shivvr)
            # Smell sense — ambient pattern detection from SKG
            await _smell_sense(ferricula, shivvr)
            if random.random() < 0.6:
                await _dream_reflection(
                    ferricula, shivvr, name, api_key, model,
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
                    ferricula, shivvr, name, api_key, model,
                    identity, interrupt_callback,
                )
                thought_count += 1
            elif reservoir >= ENTROPY_THINK_THRESHOLD:
                # Moderate entropy — a thought surfaces
                await _spontaneous_thought(
                    ferricula, shivvr, name, api_key, model,
                    identity, interrupt_callback,
                )
                thought_count += 1
            # Below threshold: quiet mind. The radio is silent. So is the agent.


async def _spontaneous_thought(
    ferricula, shivvr, name, api_key, model, identity, callback,
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

        # Ask the LLM for a brief internal reaction — no identity labels
        system = (
            "You are the dreamer's inner monologue. Not speaking to anyone. "
            "Just a thought surfacing. One or two sentences max. "
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
            vec = await shivvr.embed(thought[:200])
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
    ferricula, shivvr, name, api_key, model, identity, callback,
):
    """Synesthetic dream — all six senses feed the vision."""
    try:
        report = await ferricula.dream_latest()

        # ── Gather from all senses ──

        # Hearing + seeing + thinking: memories that shifted
        changed_ids = []
        if report.decayed_ids:
            changed_ids.extend(report.decayed_ids[:8])
        if report.consolidated_ids:
            changed_ids.extend(report.consolidated_ids[:4])
        if report.forgiven_ids:
            changed_ids.extend(report.forgiven_ids[:4])

        memory_fragments = []
        for mid in changed_ids[:12]:
            try:
                row = await ferricula.get_row(mid)
                text = row.get("tags", {}).get("text", "")
                channel = row.get("tags", {}).get("channel", "")
                if text and len(text) >= 5:
                    memory_fragments.append((channel, text[:100]))
            except Exception:
                continue

        if not memory_fragments:
            return

        # Smell: ambient emerging patterns
        smell_line = ""
        if report.skg_emerging:
            pairs = [p.replace("~", " and ") for p in report.skg_emerging[:3]]
            smell_line = "A faint scent of connection between: " + ", ".join(pairs)

        # Body: agent state
        body_line = ""
        try:
            status = await ferricula.status()
            ks_pct = (status.keystones / max(status.active, 1)) * 100
            if ks_pct > 80:
                body_line = "The body feels dense, anchored, heavy with permanence."
            elif ks_pct > 50:
                body_line = "The body feels balanced, half-solid, half-fluid."
            else:
                body_line = "The body feels light, transient, mostly passing through."
        except Exception:
            pass

        # Build the sensory dream prompt — NO stats, NO node counts, NO graph jargon
        sense_lines = []
        for channel, text in memory_fragments[:6]:
            sense_lines.append(f"- {text}")

        prompt_parts = [
            "These sensations passed through during sleep:",
            "\n".join(sense_lines),
        ]
        if body_line:
            prompt_parts.append(body_line)
        if smell_line:
            prompt_parts.append(smell_line)
        prompt_parts.append(
            "\nDescribe what you saw. A vivid scene. Two sentences. "
            "No abstractions, no metaphors about networks or graphs. "
            "Just the image."
        )

        system = "\n".join(prompt_parts)

        # ── Generate dream text via LLM ──
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

        # ── Generate dream image via Gemini (if key available) ──
        dream_image_path = None
        gemini_key = os.environ.get("GOOGLE_API_KEY", "")
        if gemini_key and random.random() < 0.7:
            try:
                image_prompt = (
                    f"Dreamlike surreal painting: {dream_text} "
                    "Ethereal, vivid colors, no text, no UI, no diagrams."
                )
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"gemini-2.0-flash-exp:generateContent?key={gemini_key}",
                        json={
                            "contents": [{"parts": [{"text": image_prompt}]}],
                            "generationConfig": {
                                "responseModalities": ["image", "text"],
                                "imageSizes": ["512x512"],
                            },
                        },
                        timeout=60,
                    )
                    resp.raise_for_status()
                    img_data = resp.json()

                # Extract base64 image if present
                for candidate in img_data.get("candidates", []):
                    for part in candidate.get("content", {}).get("parts", []):
                        if "inlineData" in part:
                            import base64
                            img_bytes = base64.b64decode(
                                part["inlineData"]["data"]
                            )
                            ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
                            dream_dir = Path(
                                os.environ.get("DREAM_DIR", "dreams")
                            )
                            dream_dir.mkdir(parents=True, exist_ok=True)
                            dream_image_path = dream_dir / f"dream_{ts}.png"
                            dream_image_path.write_bytes(img_bytes)
                            callback(
                                f"  [dream image saved: {dream_image_path}]\n"
                            )
                            break
            except Exception:
                pass  # image generation is best-effort

        # ── Record dream to journal ──
        dream_log = Path(os.environ.get("DREAM_LOG", "dreams.jsonl"))
        entry = {
            "agent": name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": "dream",
            "description": dream_text,
            "image": str(dream_image_path) if dream_image_path else None,
            "senses": {
                "fragments": [t for _, t in memory_fragments[:6]],
                "body": body_line,
                "smell": smell_line,
                "emerging": report.skg_emerging[:3],
            },
            "decayed": report.decayed,
            "consolidated": report.consolidated,
        }
        with open(dream_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # ── Remember the dream as a seeing-channel memory ──
        if shivvr and random.random() < 0.7:
            try:
                dream_mem = f"[dream] {dream_text[:180]}"
                if dream_image_path:
                    dream_mem += f" [image:{dream_image_path.name}]"
                vec = await shivvr.embed(dream_mem[:200])
                dream_mid = int(time.time() * 1000) % (2**31)
                row = {
                    "id": dream_mid,
                    "tags": {
                        "channel": "seeing",
                        "type": "dream",
                        "text": dream_mem[:200],
                    },
                    "vector": [float(v) for v in vec],
                    "decay_alpha": 0.015,
                    "importance": 0.3,
                }
                await ferricula._post("remember", json.dumps(row))
            except Exception:
                pass

    except Exception:
        pass


async def _curiosity_search(
    ferricula, shivvr, name, api_key, model, identity, callback,
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

        # Ask the LLM what the agent would want to search for — no identity
        system = (
            "You are the agent. Given this memory fragment, what would you "
            "want to look up? Reply with ONLY a search query, nothing else. "
            "5 words max. If nothing interests you, reply with just 'pass'."
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
            vec = await shivvr.embed(search_mem[:200])
            await ferricula.remember(
                search_mem[:200], vec,
                channel="thinking", decay_alpha=0.015,
            )
        except Exception:
            pass

    except Exception:
        pass


async def _body_sense(ferricula, shivvr):
    """Interoception — the agent samples its own vital signs after a dream."""
    try:
        status = await ferricula.status()
        report = await ferricula.dream_latest()

        total = status.active + status.forgiven + status.archived
        ks_pct = (status.keystones / max(status.active, 1)) * 100
        edge_density = status.graph_edges / max(status.graph_nodes, 1)

        body_text = (
            f"body: active={status.active} forgiven={status.forgiven} "
            f"archived={status.archived} keystones={status.keystones} "
            f"ks_pct={ks_pct:.0f}% edges={status.graph_edges} "
            f"density={edge_density:.1f} heat={getattr(status, 'heat', 0)}"
        )

        if shivvr:
            vec = await shivvr.embed(body_text[:200])
            await ferricula.remember(
                body_text[:200], vec,
                channel="body", decay_alpha=0.020,
            )
    except Exception:
        pass


async def _smell_sense(ferricula, shivvr):
    """Ambient detection — emerging patterns from the SKG, sensed before seen."""
    try:
        report = await ferricula.dream_latest()

        if not report.skg_emerging and not report.skg_decaying:
            return

        parts = []
        if report.skg_emerging:
            pairs = ", ".join(report.skg_emerging[:5])
            parts.append(f"emerging: {pairs}")
        if report.skg_decaying:
            pairs = ", ".join(report.skg_decaying[:5])
            parts.append(f"fading: {pairs}")

        smell_text = "ambient: " + " | ".join(parts)

        if shivvr:
            vec = await shivvr.embed(smell_text[:200])
            await ferricula.remember(
                smell_text[:200], vec,
                channel="smell", decay_alpha=0.020,
            )
    except Exception:
        pass
