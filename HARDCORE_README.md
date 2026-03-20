# HARDCORE_README.md

Technical setup guide. No fluff.

---

## Prerequisites

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.10+ | Arena orchestrator, CLI, TUI |
| Docker | 29+ | ferricula containers |
| ferricula image | `gcr.io/gnosis-459403/ferricula:latest` | Memory engine per agent |
| shivvr | Running on network | Embedding (gtr-t5-base 768d) + vec2text inversion |
| Anthropic API key | `AGENT_KEY` env var | LLM for agent reasoning + query rewriting |
| sdr-random (optional) | Running on host with RTL-SDR | Hardware entropy for dream cycles |

## Service topology

```
                    ┌─────────────────────┐
                    │   sdr-random :9090  │  bare metal (USB access to RTL-SDR)
                    │   /api/entropy      │
                    └─────────┬───────────┘
                              │
    ┌─────────────────────────┼─────────────────────────┐
    │                         │                         │
    ▼                         ▼                         ▼
┌──────────┐          ┌──────────┐              ┌──────────┐
│ agent:   │          │ agent:   │              │ agent:   │
│ Trek     │          │ Grace    │    ...       │ Scholar  │
│ :8764    │          │ :8763    │              │ :8770    │
└────┬─────┘          └────┬─────┘              └────┬─────┘
     │                     │                         │
     └─────────────────────┼─────────────────────────┘
                           │
                    ┌──────┴──────┐
                    │   shivvr   │
                    │            │
                    │ :8080      │
                    │ gtr-t5-base│
                    │ 768d ONNX  │
                    └─────────────┘
```

All ferricula containers talk to the same shivvr instance for embedding. Each container has its own data volume (WAL + snapshots). sdr-random runs bare-metal because it needs USB access to the RTL-SDR dongle.

## Install

```bash
git clone git@github.com:DeepBlueDynamics/ferricula-arena.git
cd ferricula-arena
pip install -e .
```

Or without install:
```bash
python -m arena.cli create --template agents/reader.toml --name Scholar --port 8770
```

## Pull the ferricula image

```bash
docker pull gcr.io/gnosis-459403/ferricula:latest
```

Image is public. No auth needed. ~30MB compressed (debian-slim + static Rust binary).

## Verify shivvr is reachable

```bash
curl http://your-shivvr-host:8080/health
# Should return: {"status":"ok","models":[{"name":"gtr-t5-base",...}]}

# Test embedding:
curl -s -X POST http://your-shivvr-host:8080/memory/_mcp/ingest \
  -H 'Content-Type: application/json' \
  -d '{"text":"test"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'dim={len(d[\"chunks\"][0][\"embedding\"])}')"
# Should print: dim=768
```

The embed endpoint is `/memory/_mcp/ingest`, NOT `/embed`. Returns `{"chunks":[{"embedding":[...]}]}`.

## Create an agent

### From template:
```bash
arena create --template agents/reader.toml --name "Scholar" --port 8770
```

This:
1. Pulls `gcr.io/gnosis-459403/ferricula:latest` if not present
2. Creates Docker volume `scholar-data`
3. Starts container with `--network host` (or bridge with appropriate env vars)
4. Sets `PORT`, `CHONK_URL`, `RADIO_URL`, `CLOCK_TICK_SECS` from template
5. Waits for `/status` to return 200
6. Prints identity (hexagram, zodiac, archetypes)

### Manual (no arena CLI):
```bash
docker run -d \
  --name scholar \
  --network host \
  -e PORT=8770 \
  -e CHONK_URL=http://localhost:8080 \
  -e RADIO_URL=http://localhost:9090 \
  -e CLOCK_TICK_SECS=43200 \
  -v scholar-data:/data \
  gcr.io/gnosis-459403/ferricula

# Verify:
curl http://localhost:8770/status
curl http://localhost:8770/identity
curl http://localhost:8770/        # Dashboard (HTML)
```

## Network modes

### `--network host` (recommended on Linux)
Container shares host network. `localhost:8080` reaches shivvr, `localhost:9090` reaches sdr-random. No port mapping needed — set `PORT=8770` and it listens on host `8770` directly.

### Bridge networking (Docker Desktop on Mac/Windows)
```bash
docker run -d \
  --name scholar \
  -p 8770:8770 \
  -e PORT=8770 \
  -e CHONK_URL=http://host.docker.internal:8080 \
  -e RADIO_URL=http://host.docker.internal:9090 \
  -e CLOCK_TICK_SECS=43200 \
  -v scholar-data:/data \
  gcr.io/gnosis-459403/ferricula
```

Use `host.docker.internal` for services on the host. On Linux bridge, use `172.17.0.1` or add `--add-host=host.docker.internal:host-gateway`.

## Train an agent

```bash
arena train --agent Scholar --dataset ./papers/ --dreams 5
```

### What happens:

1. **Scan** — finds all `.txt`, `.md`, `.pdf` files in the dataset directory
2. **Chunk** — sends each file to shivvr `/memory/_mcp/ingest` for chunking + embedding
3. **Classify** — matches chunks against `keystone_patterns` from the agent template
4. **Ingest** — POSTs to ferricula `/remember` with:
   - `channel`: "hearing" (primary content) or "seeing" (supplementary)
   - `keystone`: true if matched keystone patterns
   - `emotion`: classified from content tone
   - `importance`: 0.0-1.0 based on pattern match density
5. **Seed graph** — connects chunks that share terms or co-occur in the same document
6. **Fast-forward** — runs N dream cycles via `/offer` with 64 bytes entropy each:
   - Decay ticks on all non-keystone memories
   - Consolidation merges similar vectors (cosine > 0.85)
   - Semantic edge discovery by Intuition archetype
   - SKG Weber bracket update on term pairs
   - Keystone review by Ethics archetype
7. **Advocate audit** — challenges random keystones, identifies gaps

### Keystone classification

Keystones are decay-immune. The template defines `keystone_patterns` as regex patterns. A chunk becomes a keystone if:
- It matches 3+ patterns, OR
- It matches 2+ patterns AND mentions 2+ entities from the focus list

Keystone decay alpha: `0.003` (effectively immortal at 12hr dream cycles).
Normal decay alpha: `0.010` (fidelity halves in ~70 dream cycles).

## Advocate audit

```bash
arena audit --agent Scholar
```

The advocate:

1. **Keystone review** — recalls each keystone, checks fidelity > threshold (default 0.95)
2. **Random challenge** — recalls `challenge_rate` fraction of all memories, checks coherence
3. **Gap analysis** — compares agent's term index against dataset term frequency; flags missing high-frequency terms
4. **Recommendations** — outputs a report:
   ```
   PROMOTE: 3 memories (high recall count, fidelity > 0.95, not yet keystoned)
   DEMOTE:  1 keystone (fidelity dropped, 0 recalls in 30 days)
   GAPS:    ["weber bracket", "action at distance"] missing from memory
   ```

## Dream configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `CLOCK_TICK_SECS` | 60 | Seconds between clock polls |
| `DREAM_THRESHOLD_BYTES` | 16 | Entropy bytes needed to trigger a dream |
| `RADIO_URL` | `http://localhost:9080` | sdr-random endpoint for entropy |

At 64 bytes per poll (sdr-random default), a dream triggers every tick. Set `CLOCK_TICK_SECS=43200` for twice-daily dreams.

Without `RADIO_URL` or if sdr-random is offline, dreams only happen via manual `/offer` or `arena train --dreams N`.

### Entropy math

```
entropy_intensity = bytes_accumulated / max_bytes
max_bytes = DREAM_THRESHOLD_BYTES (but reservoir can exceed)

intensity < 0.25  → only decay tick (no archetypes)
intensity 0.25-0.75 → Intuition + Fortune active
intensity >= 0.75 → all 5 archetypes (full dream)
```

## ferricula HTTP API (per agent)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | HTML dashboard (identity, stats, graph) |
| GET | `/status` | JSON memory/graph counts |
| GET | `/identity` | Hexagram, zodiac, archetypes, emotions |
| GET | `/clock` | Ticks, dreams, entropy lifetime, radio status |
| GET | `/inspect/:id` | Single memory details |
| GET | `/neighbors/:id` | Graph neighbors (shows `->` for causal, `<->` for semantic) |
| GET | `/terms` | Prime tree term index |
| GET | `/skg` | Semantic Knowledge Graph — Weber brackets |
| GET | `/skg/:term` | SKG edges for a specific term |
| POST | `/remember` | Store memory (JSON: id, tags, vector) |
| POST | `/recall` | Search (JSON: query text or SQL) |
| POST | `/dream` | Manual dream cycle |
| POST | `/offer` | Inject entropy hex string, triggers dream |
| POST | `/connect` | Create edge (JSON: a, b, label, kind) |
| POST | `/disconnect` | Remove edge (JSON: a, b) |
| POST | `/keystone/:id` | Toggle keystone status |
| POST | `/checkpoint` | Flush WAL to snapshot |
| POST | `/search` | BM25 full-text search |

### Edge kinds

```bash
# Semantic (bidirectional):
curl -X POST http://localhost:8770/connect \
  -H 'Content-Type: application/json' \
  -d '{"a": 1, "b": 2, "label": "related", "kind": "semantic"}'

# Causal (directed, a -> b only):
curl -X POST http://localhost:8770/connect \
  -H 'Content-Type: application/json' \
  -d '{"a": 1, "b": 2, "label": "caused", "kind": "causal"}'
```

Causal edges enforce the arrow of time. The `to` node cannot traverse backward to the `from` node via `neighbors()`. Used for consolidation audit trails (survivor -> absorbed) and explicit causal links.

## Data persistence

Each agent's data lives in a Docker volume:
```
/data/
  identity.json       # Cast once at creation, deterministic from entropy
  snapshot_v4.bin      # Full state: rows, records, edges, prime tree, SKG
  wal.log              # Write-ahead log (auto-checkpoints at 64MB)
```

Snapshots use postcard binary serialization. V4 format includes `EdgeKind` on edges. Backward-compatible migration from V1/V2/V3.

### Backup an agent
```bash
docker run --rm -v scholar-data:/data alpine tar czf - -C /data . > scholar-backup.tar.gz
```

### Restore to another host
```bash
cat scholar-backup.tar.gz | ssh user@host "docker volume create scholar-data && docker run --rm -i -v scholar-data:/data alpine tar xzf - -C /data"
```

### Move an agent between machines
```bash
# Export
docker run --rm -v scholar-data:/data alpine tar czf - -C /data . | \
  ssh user@target "docker volume create scholar-data && docker run --rm -i -v scholar-data:/data alpine tar xzf - -C /data"

# Start on target
ssh user@target "docker run -d --name scholar --network host -e PORT=8770 -e CHONK_URL=http://localhost:8080 -v scholar-data:/data gcr.io/gnosis-459403/ferricula"
```

## MCP integration

Each agent can be accessed via the ferricula MCP tool from Claude Code or any MCP-compatible client.

### Per-agent .mcp.json
```json
{
  "mcpServers": {
    "ferricula": {
      "type": "stdio",
      "command": "python3",
      "args": ["path/to/ferricula-mcp.py"],
      "env": {
        "FERRICULA_SURFACE": "all",
        "FERRICULA_URL": "http://localhost:8770",
        "CHONK_URL": "http://localhost:8080",
        "RADIO_URL": "http://localhost:9090"
      }
    }
  }
}
```

### Multi-agent via target parameter
Any tool call accepts `target="8770"` or `target="scholar"` to route to a specific agent:
```
ferricula_recall(query="weber force law", target="8770")
ferricula_remember(text="...", target="8764")
```

## Prompt packs

Drop DIYClaw prompt packs into `packs/`. The supervisor loads them at agent creation and injects them into the LLM system prompt for that agent's personality.

```
packs/
  weber-scholar/
    base_system.txt
    agents/
      intuition.txt
      ethics.txt
    memory.txt
    execution.txt
```

## Troubleshooting

### `radio=disconnected` in clock output
The clock resolved `localhost` via `SocketAddr::parse` which fails on hostnames. Fixed in v0.5.0 — uses `ToSocketAddrs` now. Pull latest image.

### `shivvr not reachable`
The MCP tool (Python side) calls shivvr for embedding, not the container. Check `CHONK_URL` in your `.mcp.json`, not the container env. The container's `CHONK_URL` is only used by the inversion pipeline during dreams.

### Recall returns SQL parser errors
Freeform queries with "and"/"or" were being parsed as SQL boolean expressions. Fixed in v0.5.0 — the planner now only treats these as SQL if the text also contains `=`. Pull latest image or set `AGENT_KEY` for LLM query rewriting.

### `embed() failed: shivvr did not return a vector`
shivvr's embed endpoint is `/memory/_mcp/ingest`, NOT `/embed`. Check that shivvr is healthy: `curl http://host:8080/health`. If GPU errors, restart shivvr or set CPU fallback.

### Container can't reach host services (bridge networking)
Use `host.docker.internal` or `172.17.0.1` instead of `localhost`. Or use `--network host` on Linux.

---

**Deep Blue Dynamics** | [ferricula.com](https://ferricula.com)
