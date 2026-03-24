"""HTTP clients for ferricula and shivvr (embedding service).

Async via httpx. Response parsing adapted from the original arena clients.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx


# ── Response dataclasses ────────────────────────────────────────────────

@dataclass
class DreamReport:
    ticks: int = 0
    decayed: int = 0
    forgiven: int = 0
    archived: int = 0
    consolidated: int = 0
    pruned: int = 0
    ghost_echoes: int = 0
    keystones_reviewed: int = 0
    edges_created: int = 0
    keystones_promoted: int = 0
    active_archetypes: list[str] = field(default_factory=list)
    decayed_ids: list[int] = field(default_factory=list)
    forgiven_ids: list[int] = field(default_factory=list)
    consolidated_ids: list[int] = field(default_factory=list)
    skg_emerging: list[str] = field(default_factory=list)
    skg_decaying: list[str] = field(default_factory=list)


@dataclass
class RecallHit:
    id: int = 0
    fidelity: float = 1.0
    recalls: int = 0


@dataclass
class InspectResult:
    id: int = 0
    state: str = "Active"
    fidelity: float = 1.0
    decay_alpha: float = 0.01
    effective_alpha: float = 0.01
    keystone: bool = False
    recalls: int = 0
    consolidation_depth: int = 0
    importance: float = 0.0
    emotion: str = "-"
    degree: int = 0


@dataclass
class StatusResult:
    rows: int = 0
    memories: int = 0
    active: int = 0
    forgiven: int = 0
    archived: int = 0
    keystones: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0


# ── Response parsing ────────────────────────────────────────────────────

def _unwrap(resp_text: str) -> str:
    """Unwrap {"result": "..."} response, return inner string."""
    try:
        data = json.loads(resp_text)
        if "result" in data:
            return data["result"]
        if "error" in data:
            return f"error: {data['error']}"
        return resp_text
    except (json.JSONDecodeError, TypeError):
        return resp_text


def parse_dream_report(text: str) -> DreamReport:
    inner = _unwrap(text)
    report = DreamReport()
    for key in ("ticks", "decayed", "forgiven", "archived",
                "consolidated", "pruned", "ghost_echoes", "keystones_reviewed",
                "edges_created", "keystones_promoted"):
        m = re.search(rf"{key}=(\d+)", inner)
        if m:
            setattr(report, key, int(m.group(1)))
    m = re.search(r"active_archetypes=\[([^\]]*)\]", inner)
    if m and m.group(1):
        report.active_archetypes = [s.strip() for s in m.group(1).split(",") if s.strip()]
    # Parse memory IDs affected by this dream
    for id_key in ("decayed_ids", "forgiven_ids", "consolidated_ids"):
        m = re.search(rf"{id_key}=\[([^\]]*)\]", inner)
        if m and m.group(1):
            setattr(report, id_key, [int(x) for x in m.group(1).split(",") if x.strip()])
    # Parse SKG emerging/decaying term pairs
    m = re.search(r"emerging=\[([^\]]*)\]", inner)
    if m and m.group(1):
        report.skg_emerging = [s.strip() for s in m.group(1).split(",") if s.strip()]
    m = re.search(r"decaying=\[([^\]]*)\]", inner)
    if m and m.group(1):
        report.skg_decaying = [s.strip() for s in m.group(1).split(",") if s.strip()]
    return report


def parse_recall(text: str) -> list[RecallHit]:
    inner = _unwrap(text)
    hits = []
    for m in re.finditer(r"id=(\d+)\s+fidelity=([\d.]+)\s+recalls=(\d+)", inner):
        hits.append(RecallHit(
            id=int(m.group(1)),
            fidelity=float(m.group(2)),
            recalls=int(m.group(3)),
        ))
    if not hits:
        for m in re.finditer(r"id=(\d+)", inner):
            hits.append(RecallHit(id=int(m.group(1))))
    return hits


def parse_inspect(text: str) -> InspectResult:
    inner = _unwrap(text)
    result = InspectResult()
    patterns = {
        "id": (int, r"id=(\d+)"),
        "state": (str, r"state=(\w+)"),
        "fidelity": (float, r"fidelity=([\d.]+)"),
        "decay_alpha": (float, r"decay_alpha=([\d.]+)"),
        "effective_alpha": (float, r"effective=([\d.]+)"),
        "recalls": (int, r"recalls=(\d+)"),
        "consolidation_depth": (int, r"consolidation_depth=(\d+)"),
        "importance": (float, r"importance=([\d.]+)"),
        "emotion": (str, r"emotion=(\S+)"),
        "degree": (int, r"degree=(\d+)"),
    }
    for attr, (cast, pat) in patterns.items():
        m = re.search(pat, inner)
        if m:
            setattr(result, attr, cast(m.group(1)))
    m = re.search(r"keystone=(true|false)", inner, re.IGNORECASE)
    if m:
        result.keystone = m.group(1).lower() == "true"
    return result


def parse_status(text: str) -> StatusResult:
    inner = _unwrap(text)
    result = StatusResult()
    for attr, pat in [
        ("rows", r"rows=(\d+)"),
        ("memories", r"memories=(\d+)"),
        ("active", r"active=(\d+)"),
        ("forgiven", r"forgiven=(\d+)"),
        ("archived", r"archived=(\d+)"),
        ("keystones", r"keystones=(\d+)"),
        ("graph_nodes", r"(\d+) nodes"),
        ("graph_edges", r"(\d+) edges"),
    ]:
        m = re.search(pat, inner)
        if m:
            setattr(result, attr, int(m.group(1)))
    return result


def parse_remember_id(text: str) -> Optional[int]:
    inner = _unwrap(text)
    m = re.search(r"id=(\d+)", inner)
    return int(m.group(1)) if m else None


# ── ChonkClient ─────────────────────────────────────────────────────────

class ChonkClient:
    """Async HTTP client for shivvr embedding service."""

    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url.rstrip("/")

    async def embed(self, text: str, timeout: float = 30) -> list[float]:
        """Embed a short text, return 768d vector."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/memory/_mcp/ingest",
                json={"text": text},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        if "embedding" in data:
            return data["embedding"]
        return data["chunks"][0]["embedding"]

    async def chunk_and_embed(self, text: str, timeout: float = 600) -> list[dict]:
        """Chunk and embed text. Returns list of {text, embedding}."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/memory/_mcp/ingest",
                json={"text": text},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        return [{"text": c["text"], "embedding": c["embedding"]} for c in data.get("chunks", [])]

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/health", timeout=10)
                return resp.status_code == 200
        except Exception:
            return False


# ── FerriculaClient ─────────────────────────────────────────────────────

class FerriculaClient:
    """Async HTTP client for a ferricula container instance."""

    def __init__(self, base_url: str, name: str = "agent"):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self._next_id = 1

    async def _post(self, endpoint: str, body: str = "{}",
                    timeout: float = 15) -> str:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )
            return resp.text

    async def _post_raw(self, endpoint: str, body: str,
                        timeout: float = 15) -> str:
        """POST with raw body (not JSON) — used for /offer entropy hex."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                content=body.encode("utf-8"),
                timeout=timeout,
            )
            return resp.text

    async def _get(self, endpoint: str, timeout: float = 15) -> str:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=timeout)
            return resp.text

    async def available(self) -> bool:
        try:
            resp = await self._get("status")
            return "error" not in resp.lower()[:50]
        except Exception:
            return False

    def alloc_id(self) -> int:
        mid = self._next_id
        self._next_id += 1
        return mid

    async def remember(self, text: str, vector: list[float], *,
                       channel: str = "hearing", decay_alpha: float = 0.01,
                       emotion: Optional[dict] = None, importance: float = 0.0,
                       keystone: bool = False) -> int:
        """Ingest a memory, return assigned ID."""
        mid = self.alloc_id()
        tags = {"channel": channel, "text": text[:200]}
        row: dict = {
            "id": mid,
            "tags": tags,
            "vector": [float(v) for v in vector],
            "decay_alpha": decay_alpha,
        }
        if emotion:
            row["emotion"] = emotion
        if importance:
            row["importance"] = importance
        if keystone:
            row["keystone"] = True
        await self._post("remember", json.dumps(row))
        return mid

    async def recall_vector(self, vector: list[float], k: int = 10) -> list[RecallHit]:
        """Recall by vector similarity."""
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        sql = f"SELECT id FROM docs WHERE vector_topk_cosine('{vec_str}', {k})"
        resp = await self._post("recall", json.dumps({"query": sql}))
        return parse_recall(resp)

    async def recall_text(self, text: str, chonk: ChonkClient,
                          k: int = 5) -> list[RecallHit]:
        """Embed text via shivvr, then recall by vector similarity."""
        vector = await chonk.embed(text)
        return await self.recall_vector(vector, k)

    async def dream(self) -> DreamReport:
        resp = await self._post("dream")
        return parse_dream_report(resp)

    async def dream_latest(self) -> DreamReport:
        """GET /dream/latest — last dream report without triggering a new one."""
        resp = await self._get("dream/latest")
        return parse_dream_report(resp)

    async def offer(self, entropy_hex: str) -> DreamReport:
        """POST hex entropy to /offer, triggers dream with archetype activation."""
        resp = await self._post_raw("offer", entropy_hex)
        return parse_dream_report(resp)

    async def status(self) -> StatusResult:
        resp = await self._get("status")
        return parse_status(resp)

    async def identity(self) -> dict:
        resp = await self._get("identity")
        try:
            return json.loads(resp)
        except json.JSONDecodeError:
            return {}

    async def inspect(self, mid: int) -> InspectResult:
        resp = await self._get(f"inspect/{mid}")
        return parse_inspect(resp)

    async def neighbors(self, mid: int) -> str:
        return _unwrap(await self._get(f"neighbors/{mid}"))

    async def connect(self, a: int, b: int, label: str = "related",
                      kind: str = "semantic") -> str:
        return _unwrap(await self._post(
            "connect",
            json.dumps({"a": a, "b": b, "label": label, "kind": kind}),
        ))

    async def keystone(self, mid: int) -> str:
        return _unwrap(await self._post(f"keystone/{mid}"))

    async def checkpoint(self) -> str:
        return _unwrap(await self._post("checkpoint"))

    async def search(self, query: str) -> str:
        """BM25 full-text search."""
        resp = await self._post("search", json.dumps({"query": query}))
        return _unwrap(resp)

    async def terms(self) -> str:
        return _unwrap(await self._get("terms"))

    async def get_row(self, mid: int) -> dict:
        resp = await self._get(f"get/{mid}")
        try:
            return json.loads(resp)
        except json.JSONDecodeError:
            return {"error": resp}
