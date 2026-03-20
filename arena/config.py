"""TOML config loader for agent templates."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class PersonalityConfig:
    trait: str = "Neutral"
    voice: str = "Clear and direct"
    focus: list[str] = field(default_factory=list)
    emotions: dict[str, str] = field(default_factory=lambda: {
        "primary": "interest", "secondary": "trust"
    })


@dataclass
class MemoryConfig:
    port: Optional[int] = None
    chonk_url: str = "http://nemesis:8080"
    radio_url: str = "http://nemesis:9090"
    clock_tick_secs: int = 43200
    dream_threshold_bytes: int = 16


@dataclass
class TrainingConfig:
    keystone_patterns: list[str] = field(default_factory=list)
    decay_alpha_keystone: float = 0.003
    decay_alpha_normal: float = 0.010
    dreams_per_chapter: int = 3
    chunk_size: int = 512


@dataclass
class AdvocateConfig:
    review_interval: str = "after_training"
    min_keystone_fidelity: float = 0.95
    gap_detection: bool = True
    challenge_rate: float = 0.1
    source_verification: bool = False


@dataclass
class GraphConfig:
    auto_connect: bool = False
    edge_discovery: bool = False
    causal_labels: list[str] = field(default_factory=lambda: ["caused", "preceded"])
    semantic_labels: list[str] = field(default_factory=lambda: ["related", "similar"])


@dataclass
class AgentConfig:
    """Full agent configuration parsed from a TOML template."""
    name: str = "Agent"
    role: str = "General purpose agent"
    model: str = "claude-sonnet-4-6"
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    advocate: AdvocateConfig = field(default_factory=AdvocateConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    tools: list[str] = field(default_factory=lambda: [
        "remember", "recall", "dream", "inspect", "connect", "neighbors", "status"
    ])

    @property
    def port(self) -> Optional[int]:
        return self.memory.port


def load_config(path: str | Path) -> AgentConfig:
    """Load an AgentConfig from a TOML file."""
    path = Path(path)
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    agent_section = raw.get("agent", {})
    config = AgentConfig(
        name=agent_section.get("name", path.stem.capitalize()),
        role=agent_section.get("role", "General purpose agent"),
        model=agent_section.get("model", "claude-sonnet-4-6"),
    )

    if "personality" in raw:
        p = raw["personality"]
        config.personality = PersonalityConfig(
            trait=p.get("trait", "Neutral"),
            voice=p.get("voice", "Clear and direct"),
            focus=p.get("focus", []),
            emotions=p.get("emotions", {"primary": "interest", "secondary": "trust"}),
        )

    if "memory" in raw:
        m = raw["memory"]
        config.memory = MemoryConfig(
            port=m.get("port"),
            chonk_url=m.get("chonk_url", "http://nemesis:8080"),
            radio_url=m.get("radio_url", "http://nemesis:9090"),
            clock_tick_secs=m.get("clock_tick_secs", 43200),
            dream_threshold_bytes=m.get("dream_threshold_bytes", 16),
        )

    if "training" in raw:
        t = raw["training"]
        config.training = TrainingConfig(
            keystone_patterns=t.get("keystone_patterns", []),
            decay_alpha_keystone=t.get("decay_alpha_keystone", 0.003),
            decay_alpha_normal=t.get("decay_alpha_normal", 0.010),
            dreams_per_chapter=t.get("dreams_per_chapter", 3),
            chunk_size=t.get("chunk_size", 512),
        )

    if "advocate" in raw:
        a = raw["advocate"]
        config.advocate = AdvocateConfig(
            review_interval=a.get("review_interval", "after_training"),
            min_keystone_fidelity=a.get("min_keystone_fidelity", 0.95),
            gap_detection=a.get("gap_detection", True),
            challenge_rate=a.get("challenge_rate", 0.1),
            source_verification=a.get("source_verification", False),
        )

    if "graph" in raw:
        g = raw["graph"]
        config.graph = GraphConfig(
            auto_connect=g.get("auto_connect", False),
            edge_discovery=g.get("edge_discovery", False),
            causal_labels=g.get("causal_labels", ["caused", "preceded"]),
            semantic_labels=g.get("semantic_labels", ["related", "similar"]),
        )

    if "tools" in raw:
        config.tools = raw["tools"].get("enabled", config.tools)

    return config
