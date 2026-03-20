"""Supervisor — manages the lifecycle of all arena agents.

The supervisor:
  - Creates/starts/stops/resumes agent containers
  - Maintains a persistent registry (JSON) of all agents
  - Schedules dream cycles
  - Monitors agent health (memory counts, fidelity, graph density)
  - Triggers advocate reviews after training
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .agent import Agent
from .clients import FerriculaClient, ChonkClient, StatusResult
from .config import AgentConfig, load_config

REGISTRY_DIR = Path.home() / ".arena"
REGISTRY_PATH = REGISTRY_DIR / "agents.json"


class Supervisor:
    """Manages a fleet of ferricula-backed agents."""

    def __init__(self):
        self.agents: dict[str, Agent] = {}
        self._registry: dict[str, dict] = {}
        self._load_registry()

    # ── Registry persistence ────────────────────────────────────────────

    def _load_registry(self):
        if REGISTRY_PATH.exists():
            try:
                with open(REGISTRY_PATH) as f:
                    self._registry = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._registry = {}

    def _save_registry(self):
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        # Merge live agent state into registry
        for name, agent in self.agents.items():
            self._registry[name] = agent.to_dict()
        with open(REGISTRY_PATH, "w") as f:
            json.dump(self._registry, f, indent=2)

    # ── Agent lifecycle ─────────────────────────────────────────────────

    async def create_agent(self, template_path: str, *,
                           name: Optional[str] = None,
                           port: int = 0) -> Agent:
        """Create a new agent from a TOML template.

        Spins up a ferricula Docker container, waits for readiness,
        and registers the agent.
        """
        config = load_config(template_path)
        agent_name = name or config.name

        if agent_name in self.agents:
            raise ValueError(f"Agent '{agent_name}' already exists")

        if not port:
            port = self._next_port()

        agent = Agent(config, port=port, name=agent_name)
        container_id = await agent.create()

        self.agents[agent_name] = agent
        self._save_registry()

        identity = agent.state.identity or {}
        print(f"[created] {agent_name} on :{port}")
        print(f"  container: {container_id[:12]}")
        print(f"  identity: {identity.get('hexagram', {}).get('name', '?')}")

        return agent

    async def stop_agent(self, name: str):
        """Stop an agent's container (data persists)."""
        agent = self._get_agent(name)
        await agent.stop()
        self._save_registry()
        print(f"[stopped] {name}")

    async def resume_agent(self, name: str) -> Agent:
        """Restart a stopped agent's container."""
        # Try live agents first
        if name in self.agents:
            agent = self.agents[name]
            await agent.resume()
            self._save_registry()
            print(f"[resumed] {name} on :{agent.port}")
            return agent

        # Reconstruct from registry
        if name not in self._registry:
            raise ValueError(f"Agent '{name}' not found in registry")

        reg = self._registry[name]
        # We need the original config — try to find the template
        # For now, create a minimal agent from registry data
        config = AgentConfig(name=reg.get("config_name", name))
        agent = Agent(config, port=reg["port"], name=name)
        agent.state.container_name = reg.get("container_name")
        agent.state.container_id = reg.get("container_id")
        agent.state.memories_ingested = reg.get("memories_ingested", 0)
        agent.state.total_dreams = reg.get("total_dreams", 0)
        agent.state.created_at = reg.get("created_at")

        await agent.resume()
        self.agents[name] = agent
        self._save_registry()
        print(f"[resumed] {name} on :{agent.port}")
        return agent

    async def destroy_agent(self, name: str):
        """Stop and remove an agent's container + volume. Irreversible."""
        agent = self._get_agent(name)
        await agent.destroy()
        self.agents.pop(name, None)
        self._registry.pop(name, None)
        self._save_registry()
        print(f"[destroyed] {name}")

    # ── Monitoring ──────────────────────────────────────────────────────

    async def list_agents(self) -> list[dict]:
        """List all registered agents with their status."""
        results = []
        for name, reg in self._registry.items():
            entry = {
                "name": name,
                "port": reg.get("port", 0),
                "container": reg.get("container_name", "?"),
                "model": reg.get("model", "?"),
                "memories": reg.get("memories_ingested", 0),
                "dreams": reg.get("total_dreams", 0),
                "status": "unknown",
            }

            # Check if container is actually running
            if name in self.agents and self.agents[name].ferricula:
                try:
                    if await self.agents[name].ferricula.available():
                        status = await self.agents[name].ferricula.status()
                        entry["status"] = "running"
                        entry["active_memories"] = status.active
                        entry["keystones"] = status.keystones
                        entry["graph_edges"] = status.graph_edges
                    else:
                        entry["status"] = "stopped"
                except Exception:
                    entry["status"] = "unreachable"
            else:
                # Try to probe the port
                try:
                    client = FerriculaClient(
                        f"http://localhost:{reg['port']}", name,
                    )
                    if await client.available():
                        entry["status"] = "running"
                    else:
                        entry["status"] = "stopped"
                except Exception:
                    entry["status"] = "stopped"

            results.append(entry)
        return results

    async def health(self, name: str) -> dict:
        """Get detailed health metrics for an agent."""
        agent = self._get_agent(name)
        status = await agent.status()
        identity = await agent.ferricula.identity()

        return {
            "name": name,
            "port": agent.port,
            "status": asdict(status),
            "identity": identity,
            "memories_ingested": agent.state.memories_ingested,
            "total_dreams": agent.state.total_dreams,
        }

    # ── Dream scheduling ────────────────────────────────────────────────

    async def dream_all(self, cycles: int = 1):
        """Run dream cycles on all running agents."""
        for name, agent in self.agents.items():
            if not agent.ferricula:
                continue
            try:
                if not await agent.ferricula.available():
                    continue
            except Exception:
                continue

            print(f"[dream] {name}", end="")
            for _ in range(cycles):
                report = await agent.offer()
                print(f" ~", end="")
            print(f" decayed={report.decayed} consolidated={report.consolidated}")

    # ── Internals ───────────────────────────────────────────────────────

    def _get_agent(self, name: str) -> Agent:
        if name not in self.agents:
            raise ValueError(
                f"Agent '{name}' not found. "
                f"Known agents: {list(self.agents.keys()) or list(self._registry.keys())}"
            )
        return self.agents[name]

    def _next_port(self) -> int:
        """Find the next available port starting from 8764."""
        used = {reg.get("port", 0) for reg in self._registry.values()}
        port = 8764
        while port in used:
            port += 1
        return port
