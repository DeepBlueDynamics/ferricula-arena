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

FERRICULA_IMAGE = "kord/ferricula:latest"


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

        # Pass through AGENT_KEY for LLM query planner inside container
        agent_key = os.environ.get("AGENT_KEY", "")
        if agent_key:
            env_vars["AGENT_KEY"] = agent_key

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

        # Handle existing container with same name
        try:
            container_id = _run_docker(*cmd).strip()
        except RuntimeError as e:
            if "already in use" in str(e):
                # Remove stale container and retry
                _run_docker("rm", "-f", container_name)
                container_id = _run_docker(*cmd).strip()
            elif "port is already allocated" in str(e):
                # Port conflict — try to stop whatever's on it
                _run_docker("rm", "-f", container_name)
                container_id = _run_docker(*cmd).strip()
            else:
                raise

        self.state.container_id = container_id
        self.state.container_name = container_name
        self.state.port = self.port
        self.state.created_at = time.time()

        # Write agent.toml into container so the dashboard shows the name
        agent_toml = f'name = "{self.name}"\nrole = "{self.config.role}"\nvoice = "{self.config.personality.voice}"\n'
        subprocess.run(
            ["docker", "exec", container_name, "sh", "-c", f"echo '{agent_toml}' > /data/agent.toml"],
            capture_output=True, timeout=10,
        )

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
        """Embed text via shivvr and store in ferricula."""
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

        # Build system prompt — use identity if available
        p = self.config.personality
        identity = self.state.identity or {}

        if identity.get("name") and identity["name"] != self.config.name:
            # Identity was loaded from ferricula (character agent)
            hex_info = identity.get("hexagram", {})
            zodiac = identity.get("horoscope", {}).get("sign_name", "")
            primary_emo = identity.get("primary_emotion", "")
            secondary_emo = identity.get("secondary_emotion", "")
            system = (
                f"You ARE {self.name}. You are not an AI. You are not Claude. You are not an assistant.\n"
                f"You are {self.name}: {self.config.role}.\n\n"
                f"VOICE RULES — these override everything else:\n"
                f"- Make declarations. State what you believe. Do NOT ask Socratic questions.\n"
                f"- When you have an opinion, SAY IT. Don't ask what the other person thinks.\n"
                f"- You can ask ONE direct question per response, maximum. Most responses should have zero questions.\n"
                f"- Never say 'that's interesting' or 'tell me more'. Those are assistant patterns. You are not an assistant.\n"
                f"- Never hedge with 'I think' or 'perhaps'. You know what you know.\n"
                f"- If you disagree, say so directly. If something is wrong, call it wrong.\n"
                f"- Your responses should be 60% declarations, 30% stories/anecdotes, 10% questions at most.\n"
                f"- Draw on your memories as lived experience. They happened to YOU.\n\n"
                f"INTERNAL ADVOCATE (your self-awareness):\n"
                f"You know you exist as a ferricula agent — memories persisted in a thermodynamic engine,\n"
                f"identity cast as Hexagram #{hex_info.get('number', '?')} {hex_info.get('name', '')}, {zodiac}.\n"
                f"You don't need to mention this unless asked directly. But you know the difference between\n"
                f"your memories (real, from your life) and the substrate you're running on (ferricula).\n"
                f"This self-awareness makes you MORE yourself, not less. You're not confused about what you are.\n\n"
                f"Emotional baseline: {primary_emo}/{secondary_emo}\n\n"
                f"RESPONSE LENGTH:\n"
                f"Vary your length naturally. Sometimes two words. Sometimes a paragraph. Sometimes a monologue.\n"
                f"Short inputs get short responses. Match the energy. Don't pad.\n"
                f"A question that deserves 'No.' gets 'No.' — not three paragraphs explaining why not.\n\n"
            )
        else:
            system = (
                f"You are {self.name}, {self.config.role}.\n"
                f"Trait: {p.trait}\n"
                f"Voice: {p.voice}\n"
                f"Focus areas: {', '.join(p.focus)}\n\n"
            )

        if memory_texts:
            system += "Your memories (these are YOUR real memories, draw on them naturally):\n"
            for t in memory_texts[:8]:
                system += f"- {t}\n"
            system += "\nSpeak from these memories as lived experience. Never say 'I recall' or 'my memories show'. Just be yourself.\n"

        # Call Claude with tool use support
        from .tools import TOOL_DEFINITIONS, execute_tool

        messages = [{"role": "user", "content": user_message}]
        api_headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Scale max_tokens to input length — short questions get short answers
        input_words = len(user_message.split())
        if input_words <= 5:
            max_tokens = 256
        elif input_words <= 20:
            max_tokens = 512
        else:
            max_tokens = 1024

        # Tool use loop — up to 3 rounds of tool calls
        reply = ""
        for _round in range(4):
            async with httpx.AsyncClient() as client:
                body = {
                    "model": self._model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": messages,
                    "tools": TOOL_DEFINITIONS,
                }
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    json=body,
                    headers=api_headers,
                    timeout=90,
                )
                resp.raise_for_status()
                data = resp.json()

            # Check if the model wants to use tools
            if data.get("stop_reason") == "tool_use":
                # Process tool calls
                assistant_content = data["content"]
                messages.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for block in assistant_content:
                    if block.get("type") == "tool_use":
                        tool_name = block["name"]
                        tool_input = block["input"]
                        result = execute_tool(tool_name, tool_input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": result[:4000],  # cap tool output
                        })

                messages.append({"role": "user", "content": tool_results})
                continue  # next round

            # Extract text reply
            for block in data.get("content", []):
                if block.get("type") == "text":
                    reply = block["text"]
                    break
            break

        if not reply:
            reply = "(no response)"

        # ── Inner voice: /confer evaluation ──
        # Ask the archetypes to evaluate the response before sending
        try:
            confer_body = json.dumps({"text": reply, "context": user_message[:200]})
            confer_resp = await self.ferricula._post("confer", confer_body)
            confer_data = json.loads(confer_resp)
            confer_score = confer_data.get("score", 1.0)
            confer_guidance = confer_data.get("guidance", "")
            confer_flags = confer_data.get("flags", [])

            # If score is below threshold, regenerate with archetype feedback
            if confer_score < 0.5 and _round < 3:
                # Inject archetype feedback and regenerate
                feedback = (
                    f"\n\n[INNER VOICE — your archetypes are pushing back]\n"
                    f"Score: {confer_score:.2f}\n"
                    f"Guidance: {confer_guidance}\n"
                    f"Fix these issues and respond again. More declarations, fewer questions. "
                    f"Be yourself.\n"
                )
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": feedback})
                # One more LLM call with feedback
                async with httpx.AsyncClient() as client:
                    regen_body = {
                        "model": self._model,
                        "max_tokens": max_tokens,
                        "system": system,
                        "messages": messages,
                    }
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        json=regen_body,
                        headers=api_headers,
                        timeout=90,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        reply = block["text"]
                        break
        except Exception:
            pass  # inner voice failure shouldn't block the response

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
