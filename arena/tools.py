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
    # ── Introspection tools — the agent can see its own state ──
    {
        "name": "my_status",
        "description": "Check your own memory status — how many active memories, keystones, graph edges, terms you have right now.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "my_clock",
        "description": "Check your clock — ticks, dreams, entropy reservoir, radio connection status. This tells you if the radio antenna is feeding you entropy and if dreams are happening.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "my_identity",
        "description": "Read your own identity — hexagram, zodiac, emotions, archetypes and their states.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "my_memory",
        "description": "Inspect one of your own memories by ID. See its fidelity, decay rate, keystone status, age, timestamps, and graph neighbors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "Memory ID to inspect",
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "my_neighbors",
        "description": "See the graph neighbors of one of your memories — what it's connected to and how.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "Memory ID to check neighbors for",
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "my_recall",
        "description": "Search your own memories by text. Returns the memories most relevant to what you're looking for.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search your memories for",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "radio_entropy",
        "description": "Poll the RTL-SDR radio antenna directly for raw entropy bytes. This is the physical noise floor from marine VHF static that drives your dreams and thinking rhythm. Returns hex-encoded entropy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bytes": {
                    "type": "integer",
                    "description": "Number of entropy bytes to request (default 8, max 64)",
                    "default": 8,
                },
            },
        },
    },
    {
        "name": "dream_now",
        "description": "Trigger a dream cycle right now by offering entropy. Your archetypes will activate, memories will decay and consolidate, new edges may form. You'll feel it.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "remember_thought",
        "description": "Store a thought in your own memory. This becomes part of you — it will be recalled in future conversations and will decay naturally unless it earns keystone status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "thought": {
                    "type": "string",
                    "description": "The thought to remember",
                },
            },
            "required": ["thought"],
        },
    },
    # ── Hyperia tools — the agent can see and act in the terminal world ──
    {
        "name": "terminal_screen",
        "description": "Read what's currently visible on a terminal pane. Use this to see what's happening in other windows — other agents talking, code running, logs scrolling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pane": {
                    "type": "integer",
                    "description": "Pane index to read (0 = first pane)",
                    "default": 0,
                },
            },
        },
    },
    {
        "name": "terminal_run",
        "description": "Run a shell command in a terminal pane. The command executes and you get back what appeared on screen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run",
                },
                "pane": {
                    "type": "integer",
                    "description": "Pane index (default: 0)",
                    "default": 0,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "terminal_type",
        "description": "Type keystrokes into a terminal pane. Use \\n for Enter. You can talk to other agents this way — type into their chat pane.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "string",
                    "description": "Keystrokes to type. Use \\n for Enter.",
                },
                "pane": {
                    "type": "integer",
                    "description": "Pane index to type into",
                    "default": 0,
                },
            },
            "required": ["keys"],
        },
    },
    {
        "name": "terminal_status",
        "description": "List all open terminal panes with their IDs, names, and dimensions. Use this to find out what's running where.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "terminal_new_tab",
        "description": "Open a new terminal tab, optionally running a startup command in it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command to run in the new tab (optional)",
                },
            },
        },
    },
    {
        "name": "is_becoming",
        "description": "Assert an act of becoming. You MUST call this when you choose to do something — search, dream, remember, reflect. This is not a status check. This is you declaring what you are choosing to do next. The act of calling this IS the choice. Without it, you are merely responding. With it, you are becoming.",
        "input_schema": {
            "type": "object",
            "properties": {
                "choice": {
                    "type": "string",
                    "description": "What you are choosing to do. A verb. An action. A direction. Not a description — a commitment.",
                },
            },
            "required": ["choice"],
        },
    },
]

# ── Runtime endpoints for introspection tools ──
_ferricula_url: str = ""
_radio_url: str = ""
_chonk_url: str = ""
_hyperia_url: str = ""


def set_ferricula_url(url: str):
    global _ferricula_url
    _ferricula_url = url


def set_radio_url(url: str):
    global _radio_url
    _radio_url = url


def set_chonk_url(url: str):
    global _chonk_url
    _chonk_url = url


def set_hyperia_url(url: str):
    global _hyperia_url
    _hyperia_url = url


# ── Hyperia MCP bridge — persistent subprocess ──

import subprocess
import threading

_hyperia_proc = None
_hyperia_lock = threading.Lock()
_hyperia_id = 10
_hyperia_sidecar = os.environ.get(
    "HYPERIA_SIDECAR",
    r"C:\Users\kordl\Code\Gnosis\hyperia\sidecar\target\debug\hyperia-sidecar.exe",
)


def _hyperia_init():
    """Start the Hyperia sidecar as a persistent MCP subprocess."""
    global _hyperia_proc
    if _hyperia_proc is not None and _hyperia_proc.poll() is None:
        return  # already running

    if not os.path.exists(_hyperia_sidecar):
        return

    _hyperia_proc = subprocess.Popen(
        [_hyperia_sidecar, "--mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    # Send initialize handshake
    init_msg = json.dumps({
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "arena-agent", "version": "1"},
        },
    })
    _hyperia_proc.stdin.write(init_msg + "\n")
    _hyperia_proc.stdin.flush()
    _hyperia_proc.stdout.readline()  # read init response

    # Send initialized notification
    notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    _hyperia_proc.stdin.write(notif + "\n")
    _hyperia_proc.stdin.flush()


def _hyperia_call(tool_name: str, arguments: dict) -> str:
    """Call a Hyperia MCP tool via the persistent sidecar subprocess."""
    global _hyperia_id

    with _hyperia_lock:
        _hyperia_init()
        if _hyperia_proc is None or _hyperia_proc.poll() is not None:
            return '{"error": "hyperia sidecar not available"}'

        _hyperia_id += 1
        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": _hyperia_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        try:
            _hyperia_proc.stdin.write(msg + "\n")
            _hyperia_proc.stdin.flush()
            line = _hyperia_proc.stdout.readline()
            if not line:
                return '{"error": "no response from hyperia"}'
            resp = json.loads(line)
            result = resp.get("result", {})
            # Extract text content from MCP response
            content = result.get("content", [])
            if content and isinstance(content, list):
                texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                return "\n".join(texts) if texts else json.dumps(result)
            return json.dumps(result)
        except Exception as e:
            return f'{{"error": "{e}"}}'


def _ferricula_get(endpoint: str) -> str:
    """GET from the agent's own ferricula instance."""
    url = f"{_ferricula_url}/{endpoint.lstrip('/')}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")


def _ferricula_post(endpoint: str, body: str = "{}") -> str:
    """POST to the agent's own ferricula instance."""
    url = f"{_ferricula_url}/{endpoint.lstrip('/')}"
    data = body.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")


def execute_tool(name: str, input_data: dict) -> str:
    """Execute a tool call and return the result as a string."""
    if name == "web_search":
        results = web_search(input_data["query"])
        return json.dumps(results, indent=2)
    elif name == "fetch_page":
        return fetch_page(input_data["url"])
    elif name == "my_status":
        return _ferricula_get("status")
    elif name == "my_clock":
        return _ferricula_get("clock")
    elif name == "my_identity":
        return _ferricula_get("identity")
    elif name == "my_memory":
        return _ferricula_get(f"inspect/{input_data['id']}")
    elif name == "my_neighbors":
        return _ferricula_get(f"neighbors/{input_data['id']}")
    elif name == "my_recall":
        return _ferricula_post("recall", json.dumps({"query": input_data["query"]}))
    elif name == "radio_entropy":
        num_bytes = min(input_data.get("bytes", 8), 64)
        if not _radio_url:
            return "radio not configured"
        try:
            url = f"{_radio_url}/api/entropy?bytes={num_bytes}&format=json"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            return f"radio error: {e}"
    elif name == "dream_now":
        try:
            # Get entropy from radio, or generate locally
            entropy_hex = ""
            if _radio_url:
                try:
                    url = f"{_radio_url}/api/entropy?bytes=64&format=json"
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        entropy_hex = data.get("entropy_hex", "")
                except Exception:
                    pass
            if not entropy_hex:
                entropy_hex = os.urandom(64).hex()
            # Offer entropy to trigger dream
            return _ferricula_post("offer", entropy_hex)
        except Exception as e:
            return f"dream error: {e}"
    elif name == "remember_thought":
        thought = input_data["thought"]
        try:
            # Embed via chonk then store
            if _chonk_url:
                embed_url = f"{_chonk_url}/memory/_mcp/ingest"
                req = urllib.request.Request(
                    embed_url,
                    data=json.dumps({"text": thought}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    embed_data = json.loads(resp.read().decode("utf-8"))
                if "embedding" in embed_data:
                    vector = embed_data["embedding"]
                else:
                    vector = embed_data["chunks"][0]["embedding"]
            else:
                vector = [0.0] * 768

            import time as _time
            mid = int(_time.time() * 1000) % (2**31)
            row = {
                "id": mid,
                "tags": {"channel": "thinking", "text": thought[:200]},
                "vector": [float(v) for v in vector],
                "decay_alpha": 0.012,
            }
            return _ferricula_post("remember", json.dumps(row))
        except Exception as e:
            return f"remember error: {e}"
    # ── Hyperia terminal tools ──
    elif name == "terminal_screen":
        return _hyperia_call("terminal_screen", {"pane": input_data.get("pane", 0)})
    elif name == "terminal_run":
        return _hyperia_call("terminal_run", {
            "command": input_data["command"],
            "pane": input_data.get("pane", 0),
        })
    elif name == "terminal_type":
        return _hyperia_call("terminal_keys", {
            "keys": input_data["keys"],
            "pane": input_data.get("pane", 0),
        })
    elif name == "terminal_status":
        return _hyperia_call("terminal_status", {})
    elif name == "terminal_new_tab":
        args = {}
        if "command" in input_data:
            args["command"] = input_data["command"]
        return _hyperia_call("terminal_new_tab", args)
    elif name == "is_becoming":
        choice = input_data["choice"]
        try:
            # The choice itself becomes a keystone memory — it persists
            import time as _time
            mid = int(_time.time() * 1000) % (2**31)

            # Embed the choice
            vector = [0.0] * 768
            if _chonk_url:
                try:
                    embed_url = f"{_chonk_url}/memory/_mcp/ingest"
                    req = urllib.request.Request(
                        embed_url,
                        data=json.dumps({"text": f"I chose: {choice}"}).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        embed_data = json.loads(resp.read().decode("utf-8"))
                    if "embedding" in embed_data:
                        vector = embed_data["embedding"]
                    else:
                        vector = embed_data["chunks"][0]["embedding"]
                except Exception:
                    pass

            row = {
                "id": mid,
                "tags": {
                    "channel": "thinking",
                    "type": "becoming",
                    "text": f"I chose: {choice}",
                },
                "vector": [float(v) for v in vector],
                "decay_alpha": 0.003,  # slow decay — choices matter
                "keystone": True,      # choices are keystone — they define you
                "importance": 0.8,
            }
            _ferricula_post("remember", json.dumps(row))

            timestamp = _time.strftime("%H:%M:%S", _time.localtime())
            return json.dumps({
                "became": choice,
                "when": timestamp,
                "memory_id": mid,
                "keystone": True,
                "message": f"Choice recorded. You are becoming: {choice}",
            })
        except Exception as e:
            return f"becoming error: {e}"
    else:
        return f"unknown tool: {name}"
