"""External tools for arena agents — web search, browse, etc.

These are called by the LLM via tool_use when the agent needs information
it doesn't have in memory.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
from typing import Optional


# ── Web Search (SerpAPI) ──────────────────────────────────────────────────

SERPAPI_KEY = os.environ.get("SERPAPI_API_KEY", "")

# Also try loading from .serpapi.env in cwd or parent dirs
if not SERPAPI_KEY:
    for candidate in [".serpapi.env", "../.serpapi.env", "../../.serpapi.env"]:
        try:
            with open(candidate) as f:
                for line in f:
                    if line.startswith("SERPAPI_API_KEY="):
                        SERPAPI_KEY = line.split("=", 1)[1].strip()
                        break
            if SERPAPI_KEY:
                break
        except FileNotFoundError:
            continue


def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search the web via SerpAPI. Returns list of {title, link, snippet}."""
    if not SERPAPI_KEY:
        return [{"error": "SERPAPI_API_KEY not set"}]

    params = urllib.parse.urlencode({
        "q": query,
        "api_key": SERPAPI_KEY,
        "engine": "google",
        "num": num_results,
    })
    url = f"https://serpapi.com/search.json?{params}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return [{"error": str(e)}]

    results = []
    for item in data.get("organic_results", [])[:num_results]:
        results.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


def fetch_page(url: str, max_chars: int = 10000) -> str:
    """Fetch a web page and return text content (stripped of HTML)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (ferricula-arena agent)",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"error: {e}"

    # Strip HTML tags (rough but functional)
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


# ── Tool Definitions (Anthropic tool_use format) ──────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": "Search the web for current information. Use when you need facts you don't have in memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": "Fetch and read a web page. Use to get details from a specific URL found via search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch",
                },
            },
            "required": ["url"],
        },
    },
]


def execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool call and return the result as a string."""
    if name == "web_search":
        results = web_search(input_data["query"])
        return json.dumps(results, indent=2)
    elif name == "fetch_page":
        return fetch_page(input_data["url"])
    else:
        return f"unknown tool: {name}"
