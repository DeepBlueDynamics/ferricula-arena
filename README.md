# ferricula-arena

### AI agents that remember. Forget. Dream. Wake up different.

---

Most AI agents are stateless. They process your prompt, return a response, and vanish. No memory of what they learned yesterday. No sense of what matters. No ability to let go of what doesn't.

**ferricula-arena** is different.

Every agent you create gets a living brain. Memories decay over time. Important knowledge crystallizes into keystones that resist forgetting. Similar memories merge into stronger composites. And when the radio feeds entropy from the electromagnetic spectrum, the agent dreams — consolidating, pruning, discovering connections it never explicitly made.

This isn't retrieval-augmented generation. This is thermodynamic cognition.

---

### What you get

**Agents with real memory.** Each agent runs its own [ferricula](https://ferricula.com) container — a Rust-built thermodynamic memory engine. Memories have fidelity that decays exponentially. Recall strengthens them. Neglect kills them. The lifecycle is irreversible, like physics.

**A supervisor that manages them.** Create agents from templates. Feed them documents. Schedule their dream cycles. Monitor their health. The supervisor tracks memory counts, fidelity distributions, graph density, and archetype activation across your entire fleet.

**An advocate that keeps them honest.** After training, the memory advocate audits every agent's keystones. Are they still relevant? Are there gaps? Should anything be promoted or demoted? The advocate challenges memory quality so your agents don't drift.

**Training on real data.** Point an agent at a directory of PDFs, papers, or text files. The trainer chunks, embeds, classifies, ingests, seeds the knowledge graph, and fast-forwards dream cycles to consolidate. Your agent wakes up having "read" the material — with opinions about what mattered.

**A TUI to watch them think.** Live dashboard showing every running agent. Memory stats. Dream reports. Graph metrics. Click into any agent to chat, inspect individual memories, or watch consolidation happen in real time.

---

### The dream cycle

Every ferricula agent has five archetypes that activate during dreams, gated by entropy intensity:

| Archetype | Role | Wakes at |
|-----------|------|----------|
| Intuition | Discovers semantic edges between memories | Moderate entropy |
| Fortune | Evaluates timing — reinforce or release? | Moderate entropy |
| Craft | Drives consolidation, merges similar memories | Full entropy |
| Ethics | Reviews keystones, enforces lifecycle rules | Full entropy |
| Advocate | Manages inter-agent memory sharing | Full entropy |

Dreams are fed by real hardware entropy from an RTL-SDR radio dongle via [sdr-random](https://github.com/DeepBlueDynamics/sdr-random). No radio? Dreams still run on schedule — just without the entropy modulation.

---

### Quick start

```bash
pip install ferricula-arena

# Create an agent
arena create --template reader --name "Scholar" --port 8770

# Train it on your documents
arena train --agent Scholar --dataset ./papers/ --dreams 5

# Chat with it
arena chat --agent Scholar

# Watch all agents live
arena monitor
```

---

### Agent templates

Define an agent in TOML. Personality, memory parameters, keystone patterns, graph behavior, tool access — all configurable.

```toml
[agent]
name = "Weber Scholar"
role = "19th century electrodynamics researcher"
model = "claude-sonnet-4-6"

[personality]
trait = "Methodical"
voice = "Precise, builds arguments step by step"
emotions = { primary = "interest", secondary = "trust" }

[training]
keystone_patterns = ["force law", "equation", "proof", "theorem"]
dreams_per_chapter = 3
```

Three templates included: **reader** (document analysis), **analyst** (pattern recognition and causal graphs), **researcher** (deep investigation with web access).

Build your own. Drop a DIYClaw prompt pack into `packs/` for full personality injection.

---

### The graph enforces the arrow of time

ferricula's knowledge graph supports two edge types:

- **Semantic** — bidirectional, associative. "These ideas are related."
- **Causal** — directed, one-way. "This caused that." The target cannot traverse backward to its cause.

Causal edges prevent recursive feedback loops that would trap an agent in its own past. In Buddhist terminology: no clinging. In physics: the DAG enforces causality. In practice: your agents move forward.

---

### Built on

- [ferricula](https://ferricula.com) — thermodynamic memory engine (Rust)
- [shivvr](https://github.com/DeepBlueDynamics/shivvr) — embedding + vec2text inversion (Rust, ONNX)
- [sdr-random](https://github.com/DeepBlueDynamics/sdr-random) — hardware entropy from RTL-SDR (Rust)
- Claude API — LLM reasoning (Anthropic)

---

**Deep Blue Dynamics** | [ferricula.com](https://ferricula.com) | [GitHub](https://github.com/DeepBlueDynamics)
