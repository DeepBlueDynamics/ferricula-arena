# ferricula-arena

Agent runner SDK for ferricula-backed AI agents. Each agent owns a ferricula memory container. A supervisor manages the lifecycle. An advocate audits memory quality. Agents can be trained on datasets, interact with users, and dream on schedule.

## Architecture

```
ferricula-arena/
  arena.py              # Core orchestrator — tick loop, agent lifecycle
  supervisor.py         # Supervisor agent — manages all agent cores
  advocate.py           # Memory advocate — audits keystones, challenges fidelity
  agent.py              # Base agent class — wraps ferricula + LLM
  trainer.py            # Dataset trainer — feeds documents, fast-forwards dreams
  monitor.py            # Live monitoring — TUI dashboard for all agents
  clients.py            # HTTP clients for ferricula + shivvr (from arena)
  config.py             # TOML config loader
  cli.py                # CLI entry point
  agents/               # Agent templates (TOML + optional prompt packs)
    reader.toml         # Document reader agent
    analyst.toml        # Data analyst agent
    researcher.toml     # Research agent with web access
  packs/                # DIYClaw prompt packs (user-provided)
  data/                 # Datasets for training
  logs/                 # Run logs and dream reports
```

## Core Concepts

### Agent = Ferricula Container + LLM + Personality

Each agent is:
- A ferricula Docker container (isolated memory, identity, graph)
- An LLM connection (Claude, configurable model)
- A personality config (TOML: name, role, voice, focus areas, emotions)
- A set of tools (read documents, search, remember, recall, dream)

### Supervisor Agent

The supervisor:
- Starts/stops agent containers
- Assigns datasets to agents for training
- Schedules dream cycles (configurable intervals)
- Monitors agent health (memory counts, fidelity distribution, graph density)
- Triggers advocate reviews after training runs

### Memory Advocate

The advocate:
- Runs after training (or on schedule)
- Reviews keystones: are they still relevant? Should any be demoted?
- Challenges memory quality: recall random memories, check coherence
- Identifies gaps: what important concepts are missing?
- Reports to supervisor with recommendations (promote, demote, remember more)

### Training Flow

```
1. CREATE agent   → spin up ferricula container, cast identity
2. LOAD dataset   → chunk documents via shivvr, classify keystones
3. INGEST         → remember chunks with channel/emotion/importance
4. SEED GRAPH     → connect related memories (co-occurrence, semantic)
5. FAST-FORWARD   → run N dream cycles to consolidate and decay
6. ADVOCATE       → memory quality audit, gap analysis
7. INTERACT       → agent is ready for conversation/tasks
```

### Monitoring

Live TUI (Textual) showing:
- All running agents with identity, memory stats, graph metrics
- Recent dream reports (what was consolidated, what died)
- Advocate audit results
- Interactive: select an agent, chat with it, inspect memories

## Agent Template (TOML)

```toml
[agent]
name = "Weber Scholar"
role = "19th century electrodynamics researcher"
model = "claude-sonnet-4-6"

[personality]
trait = "Methodical"
voice = "Precise, builds arguments step by step"
focus = ["weber force law", "velocity-dependent forces", "action at a distance"]
emotions = { primary = "interest", secondary = "trust" }

[memory]
port = 8770
chonk_url = "http://nemesis:8080"
radio_url = "http://nemesis:9090"
clock_tick_secs = 43200
dream_threshold_bytes = 16

[training]
keystone_patterns = ["force law", "equation", "proof", "theorem", "weber bracket"]
decay_alpha_keystone = 0.003
decay_alpha_normal = 0.010
dreams_per_chapter = 3

[tools]
enabled = ["remember", "recall", "dream", "inspect", "connect", "neighbors"]
```

## CLI

```bash
# Create and start an agent from template
arena create --template agents/reader.toml --name "Trek" --port 8764

# Train on a dataset
arena train --agent Trek --dataset data/weber_papers/ --dreams 5

# Run advocate audit
arena audit --agent Trek

# Monitor all agents
arena monitor

# Chat with an agent
arena chat --agent Trek

# List running agents
arena list

# Stop an agent (container stays, data persists)
arena stop --agent Trek

# Resume (restart container, memory intact)
arena resume --agent Trek
```

## Dependencies

- Python 3.10+
- Docker (ferricula containers)
- shivvr (embedding service)
- Anthropic API key (AGENT_KEY for LLM)
- Optional: sdr-random (entropy source for dreams)
- textual (TUI framework)
- tomli (config parsing)
- httpx (async HTTP client)
