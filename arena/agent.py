"""Base agent class — wraps ferricula container + LLM + personality.

Each Agent is:
  - A ferricula Docker container (isolated memory, identity, graph)
  - An LLM connection (Claude, configurable model)
  - A personality config (TOML: name, role, voice, focus, emotions)
  - A set of tools (remember, recall, dream, inspect, connect, neighbors)
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .clients import ChonkClient, FerriculaClient, DreamReport, StatusResult
from .config import AgentConfig, load_config

FERRICULA_IMAGE = "gcr.io/gnosis-459403/ferricula:latest"


@dataclass
class AgentState:
    """Runtime state for a running agent."""
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    port: int = 0
    identity: Optional[dict] = None
    memories_ingested: int = 0
    total_dreams: int = 0
    created_at: Optional[float] = None


class Agent:
    """A ferricula-backed AI agent with persistent thermodynamic memory."""

    def __init__(self, config: AgentConfig, *, port: int = 0,
                 name: Optional[str] = None):
        self.config = config
        self.name = name or config.name
        self.port = port or config.port or 0
        self.state = AgentState()

        # Clients — initialized when container starts
        self.ferricula: Optional[FerriculaClient] = None
        self.chonk = ChonkClient(config.memory.chonk_url)

        # LLM
        self._api_key = os.environ.get("AGENT_KEY", "")
        self._model = config.model

    @classmethod
    def from_template(cls, template_path: str, *, port: int = 0,
                      name: Optional[str] = None) -> Agent:
        """Create an Agent from a TOML template file."""
        config = load_config(template_path)
        return cls(config, port=port, name=name)

    # ── Container lifecycle ─────────────────────────────────────────────

    async def create(self, *, pull: bool = True) -> str:
        """Create and start the ferricula Docker container.

        Returns the container ID.
        """
        if not self.port:
            raise ValueError("Port must be set before creating container")

        container_name = self.name.lower().replace(" ", "-")

        if pull:
            _run_docker("pull", FERRICULA_IMAGE)

        # Create data volume
        volume_name = f"{container_name}-data"
        _run_docker("volume", "create", volume_name)

        # Determine network mode
        is_linux = platform.system() == "Linux"

        env_vars = {
            "PORT": str(self.port),
            "CHONK_URL": self.config.memory.chonk_url,
            "RADIO_URL": self.config.memory.radio_url,
            "CLOCK_TICK_SECS": str(self.config.memory.clock_tick_secs),
            "DREAM_THRESHOLD_BYTES": str(self.config.memory.dream_threshold_bytes),
        }

        cmd = ["run", "-d", "--name", container_name]
        for k, v in env_vars.items():
            cmd.extend(["-e", f"{k}={v}"])
        cmd.extend(["-v", f"{volume_name}:/data"])

        if is_linux:
            cmd.append("--network=host")
        else:
            cmd.extend(["-p", f"{self.port}:{self.port}"])
            # Rewrite localhost URLs to host.docker.internal for bridge networking
            if "localhost" in env_vars["CHONK_URL"]:
                chonk_bridge = env_vars["CHONK_URL"].replace("localhost", "host.docker.internal")
                cmd.extend(["-e", f"CHONK_URL={chonk_bridge}"])
            if "localhost" in env_vars["RADIO_URL"]:
                radio_bridge = env_vars["RADIO_URL"].replace("localhost", "host.docker.internal")
                cmd.extend(["-e", f"RADIO_URL={radio_bridge}"])

        cmd.append(FERRICULA_IMAGE)
        container_id = _run_docker(*cmd).strip()

        self.state.container_id = container_id
        self.state.container_name = container_name
        self.state.port = self.port
        self.state.created_at = time.time()

        # Initialize client
        self.ferricula = FerriculaClient(
            f"http://localhost:{self.port}", self.name,
        )

        # Wait for container to be ready
        await self._wait_ready()

        # Read identity
        self.state.identity = await self.ferricula.identity()

        return container_id

    async def _wait_ready(self, timeout: float = 30):
        """Poll /status until the container responds."""
        if not self.ferricula:
            raise RuntimeError("No ferricula client")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if await self.ferricula.available():
                return
            await _async_sleep(0.5)
        raise TimeoutError(
            f"Container {self.name} not ready after {timeout}s"
        )

    async def stop(self):
        """Stop the container (data persists in volume)."""
        if self.state.container_name:
            _run_docker("stop", self.state.container_name)

    async def resume(self):
        """Restart a stopped container."""
        if self.state.container_name:
            _run_docker("start", self.state.container_name)
            self.ferricula = FerriculaClient(
                f"http://localhost:{self.port}", self.name,
            )
            await self._wait_ready()
            self.state.identity = await self.ferricula.identity()

    async def destroy(self):
        """Stop and remove container + volume. Irreversible."""
        name = self.state.container_name
        if name:
            _run_docker("rm", "-f", name)
            _run_docker("volume", "rm", "-f", f"{name}-data")
            self.state.container_id = None

    # ── Memory operations ───────────────────────────────────────────────

    async def remember(self, text: str, *, channel: str = "hearing",
                       keystone: bool = False,
                       importance: float = 0.0) -> int:
        """Embed text via chonk and store in ferricula."""
        self._require_running()
        vector = await self.chonk.embed(text)
        alpha = (self.config.training.decay_alpha_keystone if keystone
                 else self.config.training.decay_alpha_normal)
        mid = await self.ferricula.remember(
            text, vector,
            channel=channel,
            decay_alpha=alpha,
            keystone=keystone,
            importance=importance,
        )
        self.state.memories_ingested += 1
        return mid

    async def recall(self, query: str, k: int = 5) -> list[dict]:
        """Recall memories by semantic similarity. Returns text + metadata."""
        self._require_running()
        hits = await self.ferricula.recall_text(query, self.chonk, k=k)
        results = []
        for hit in hits:
            row = await self.ferricula.get_row(hit.id)
            results.append({
                "id": hit.id,
                "fidelity": hit.fidelity,
                "recalls": hit.recalls,
                "text": row.get("tags", {}).get("text", ""),
            })
        return results

    async def dream(self) -> DreamReport:
        """Trigger a manual dream cycle."""
        self._require_running()
        report = await self.ferricula.dream()
        self.state.total_dreams += 1
        return report

    async def offer(self, entropy_hex: Optional[str] = None) -> DreamReport:
        """Inject entropy and trigger dream with archetype activation.

        If no entropy provided, generates 64 bytes from os.urandom.
        """
        self._require_running()
        if entropy_hex is None:
            entropy_hex = os.urandom(64).hex()
        report = await self.ferricula.offer(entropy_hex)
        self.state.total_dreams += 1
        return report

    async def status(self) -> StatusResult:
        self._require_running()
        return await self.ferricula.status()

    async def inspect(self, mid: int):
        self._require_running()
        return await self.ferricula.inspect(mid)

    # ── LLM chat ────────────────────────────────────────────────────────

    async def chat(self, user_message: str, *,
                   recall_k: int = 5) -> str:
        """Memory-augmented LLM response.

        1. Recall relevant memories
        2. Build system prompt with personality + memories
        3. Call Claude API
        4. Remember the exchange
        """
        self._require_running()
        if not self._api_key:
            raise RuntimeError("AGENT_KEY env var not set")

        # Recall relevant memories
        memories = await self.recall(user_message, k=recall_k)
        memory_texts = [m["text"] for m in memories if m["text"]]

        # Build system prompt
        p = self.config.personality
        system = (
            f"You are {self.name}, {self.config.role}.\n"
            f"Trait: {p.trait}\n"
            f"Voice: {p.voice}\n"
            f"Focus areas: {', '.join(p.focus)}\n\n"
        )
        if memory_texts:
            system += "Your relevant memories:\n"
            for t in memory_texts[:5]:
                system += f"- {t}\n"
            system += "\nDraw on these memories naturally. Don't list them.\n"

        # Call Claude
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": self._model,
                    "max_tokens": 1024,
                    "system": system,
                    "messages": [{"role": "user", "content": user_message}],
                },
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

        reply = data["content"][0]["text"]

        # Remember the exchange
        exchange = f"User asked: {user_message[:100]} | I replied: {reply[:100]}"
        await self.remember(exchange, channel="thinking")

        return reply

    # ── Internals ───────────────────────────────────────────────────────

    def _require_running(self):
        if not self.ferricula:
            raise RuntimeError(
                f"Agent {self.name} has no ferricula client. "
                f"Call create() or resume() first."
            )

    def to_dict(self) -> dict:
        """Serialize agent state for registry persistence."""
        return {
            "name": self.name,
            "port": self.port,
            "container_id": self.state.container_id,
            "container_name": self.state.container_name,
            "model": self._model,
            "config_name": self.config.name,
            "memories_ingested": self.state.memories_ingested,
            "total_dreams": self.state.total_dreams,
            "created_at": self.state.created_at,
        }


# ── Helpers ─────────────────────────────────────────────────────────────

def _run_docker(*args: str) -> str:
    """Run a docker command, return stdout."""
    cmd = ["docker"] + list(args)
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker {' '.join(args)} failed:\n{result.stderr.strip()}"
        )
    return result.stdout


async def _async_sleep(seconds: float):
    """Async sleep without importing asyncio at module level."""
    import asyncio
    await asyncio.sleep(seconds)
