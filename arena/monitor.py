"""Live TUI dashboard for ferricula-arena agents.

Shows all running agents with identity, memory stats, graph metrics,
last dream report, and fidelity distribution. Select an agent to chat inline.
Refreshes every 15 seconds.

Requires: pip install ferricula-arena[tui]
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Log,
    Static,
)

from .clients import (
    ShivvrClient,
    DreamReport,
    FerriculaClient,
    InspectResult,
    StatusResult,
)
from .supervisor import Supervisor

REFRESH_INTERVAL = 15


# ── Agent detail panel data ─────────────────────────────────────────────

class AgentDetail:
    """Collected detail for one agent, fetched async."""

    def __init__(self, name: str, port: int):
        self.name = name
        self.port = port
        self.status: Optional[StatusResult] = None
        self.identity: dict = {}
        self.last_dream: Optional[DreamReport] = None
        self.fidelity_buckets: dict[str, int] = {}  # "0.9-1.0" -> count
        self.reachable: bool = False

    @property
    def hexagram(self) -> str:
        h = self.identity.get("hexagram", {})
        return f"{h.get('number', '?')} {h.get('name', '?')}"

    @property
    def horoscope(self) -> str:
        h = self.identity.get("horoscope", {})
        if isinstance(h, dict):
            return h.get("sign_name", "?")
        return str(h) if h else "?"

    @property
    def emotions(self) -> str:
        p = self.identity.get("primary_emotion", "?")
        s = self.identity.get("secondary_emotion", "?")
        if p != "?":
            return f"{p}/{s}"
        e = self.identity.get("emotions", {})
        return f"{e.get('primary', '?')}/{e.get('secondary', '?')}"

    @property
    def active_archetypes(self) -> list[str]:
        arcs = self.identity.get("archetypes", [])
        if isinstance(arcs, list):
            return [a.get("role", "?") for a in arcs if a.get("active") or a.get("state") not in (None, "Dormant")]
        if isinstance(arcs, dict):
            return [k for k, v in arcs.items() if isinstance(v, str) and v != "Dormant"]
        return []


async def fetch_detail(name: str, port: int) -> AgentDetail:
    """Fetch full detail for one agent."""
    detail = AgentDetail(name, port)
    client = FerriculaClient(f"http://localhost:{port}", name)

    try:
        if not await client.available():
            return detail
        detail.reachable = True
    except Exception:
        return detail

    try:
        detail.status = await client.status()
    except Exception:
        pass

    try:
        detail.identity = await client.identity()
    except Exception:
        pass

    # Sample fidelity distribution from recent memories
    try:
        buckets = {"0.0-0.3": 0, "0.3-0.6": 0, "0.6-0.9": 0, "0.9-1.0": 0}
        # Sample up to 30 random IDs from the known range
        max_id = client._next_id if client._next_id > 1 else 100
        if detail.status:
            max_id = max(max_id, detail.status.rows + 1)
        sample_ids = random.sample(
            range(1, max_id + 1), min(30, max_id),
        )
        for mid in sample_ids:
            try:
                info = await client.inspect(mid)
                if info.state != "Active":
                    continue
                f = info.fidelity
                if f >= 0.9:
                    buckets["0.9-1.0"] += 1
                elif f >= 0.6:
                    buckets["0.6-0.9"] += 1
                elif f >= 0.3:
                    buckets["0.3-0.6"] += 1
                else:
                    buckets["0.0-0.3"] += 1
            except Exception:
                continue
        detail.fidelity_buckets = buckets
    except Exception:
        pass

    return detail


# ── Widgets ─────────────────────────────────────────────────────────────

class AgentTable(DataTable):
    """Main table listing all agents."""

    COLUMNS = [
        ("Agent", 16),
        ("Port", 6),
        ("Status", 8),
        ("Active", 7),
        ("Keystones", 10),
        ("Forgiven", 9),
        ("Archived", 9),
        ("Nodes", 6),
        ("Edges", 6),
        ("Hexagram", 24),
        ("Emotions", 18),
    ]

    def on_mount(self):
        for col_name, _ in self.COLUMNS:
            self.add_column(col_name, key=col_name.lower())
        self.cursor_type = "row"


class DetailPanel(VerticalScroll):
    """Right panel showing selected agent's detail."""

    def compose(self) -> ComposeResult:
        yield Static("Select an agent", id="detail-header")
        yield Static("", id="detail-identity")
        yield Static("", id="detail-memory")
        yield Static("", id="detail-graph")
        yield Static("", id="detail-dream")
        yield Static("", id="detail-fidelity")
        yield Static("", id="detail-archetypes")

    def update_detail(self, d: Optional[AgentDetail]):
        if not d or not d.reachable:
            self._set("detail-header", "Agent unreachable" if d else "Select an agent")
            for w_id in ("detail-identity", "detail-memory", "detail-graph",
                         "detail-dream", "detail-fidelity", "detail-archetypes"):
                self._set(w_id, "")
            return

        self._set("detail-header", f"[bold]{d.name}[/bold] :{d.port}")

        self._set("detail-identity",
                   f"[dim]hexagram:[/dim]  {d.hexagram}\n"
                   f"[dim]horoscope:[/dim] {d.horoscope}\n"
                   f"[dim]emotions:[/dim]  {d.emotions}")

        s = d.status
        if s:
            self._set("detail-memory",
                       f"[dim]memories:[/dim]   {s.memories} total, "
                       f"{s.active} active, {s.forgiven} forgiven, "
                       f"{s.archived} archived\n"
                       f"[dim]keystones:[/dim]  {s.keystones}")
            self._set("detail-graph",
                       f"[dim]graph:[/dim]      {s.graph_nodes} nodes, "
                       f"{s.graph_edges} edges")

        arcs = d.active_archetypes
        arc_str = ", ".join(arcs) if arcs else "all dormant"
        self._set("detail-archetypes",
                   f"[dim]archetypes:[/dim] {arc_str}")

        # Fidelity distribution as a text histogram
        if d.fidelity_buckets:
            total = sum(d.fidelity_buckets.values()) or 1
            lines = ["[dim]fidelity distribution:[/dim]"]
            for bucket, count in d.fidelity_buckets.items():
                bar_len = int(30 * count / total) if total else 0
                bar = "█" * bar_len
                lines.append(f"  {bucket:>7}  {bar} {count}")
            self._set("detail-fidelity", "\n".join(lines))

    def _set(self, widget_id: str, text: str):
        try:
            self.query_one(f"#{widget_id}", Static).update(text)
        except NoMatches:
            pass


class ChatPanel(Vertical):
    """Bottom panel for chatting with selected agent."""

    def compose(self) -> ComposeResult:
        yield Log(id="chat-log", max_lines=200)
        yield Input(placeholder="Type a message (Enter to send, Esc to close)",
                    id="chat-input")


# ── App ─────────────────────────────────────────────────────────────────

MONITOR_CSS = """
Screen {
    layout: grid;
    grid-size: 2 2;
    grid-columns: 2fr 1fr;
    grid-rows: 1fr auto;
    background: #0c0a09;
}

#table-container {
    row-span: 1;
    column-span: 1;
    height: 100%;
    border: solid #b91c1c;
    border-title-color: #b91c1c;
    background: #1c1917;
}

AgentTable {
    height: 100%;
    background: #1c1917;
}

AgentTable > .datatable--header {
    background: #292524;
    color: #b91c1c;
    text-style: bold;
}

AgentTable > .datatable--cursor {
    background: #44403c;
    color: #fafaf9;
}

AgentTable > .datatable--even-row {
    background: #1c1917;
}

AgentTable > .datatable--odd-row {
    background: #0c0a09;
}

DetailPanel {
    row-span: 1;
    column-span: 1;
    height: 100%;
    border: solid #78716c;
    border-title-color: #b91c1c;
    padding: 1;
    background: #1c1917;
    color: #e7e5e4;
}

ChatPanel {
    row-span: 1;
    column-span: 2;
    height: auto;
    max-height: 16;
    border: solid #059669;
    border-title-color: #059669;
    display: none;
    background: #0c0a09;
}

ChatPanel.visible {
    display: block;
}

#chat-log {
    height: 12;
    background: #0c0a09;
    color: #a8a29e;
}

#chat-input {
    dock: bottom;
    background: #1c1917;
    color: #e7e5e4;
    border: tall #44403c;
}

#chat-input:focus {
    border: tall #b91c1c;
}

#detail-header {
    text-style: bold;
    color: #b91c1c;
    margin-bottom: 1;
}

Header {
    background: #b91c1c;
    color: #fafaf9;
}

Footer {
    background: #292524;
    color: #a8a29e;
}

Footer > .footer--key {
    background: #44403c;
    color: #b91c1c;
}
"""


class MonitorApp(App):
    """Live dashboard for ferricula-arena agents."""

    CSS = MONITOR_CSS
    TITLE = "FERRICULA ARENA"
    SUB_TITLE = "thermodynamic memory monitor"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("c", "toggle_chat", "Chat"),
        Binding("d", "dream_selected", "Dream"),
    ]

    selected_agent: reactive[Optional[str]] = reactive(None)

    def __init__(self, direct_agents: list[dict] | None = None):
        super().__init__()
        self.supervisor = None if direct_agents else Supervisor()
        self.direct_agents = direct_agents
        self.details: dict[str, AgentDetail] = {}
        self._refresh_timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="table-container"):
            yield AgentTable(id="agent-table")
        yield DetailPanel(id="detail-panel")
        yield ChatPanel(id="chat-panel")
        yield Footer()

    def on_mount(self):
        # Do initial poll, then schedule repeating
        self.set_timer(0.5, self._start_poll)
        self._refresh_timer = self.set_interval(
            REFRESH_INTERVAL, self._start_poll,
        )

    def _start_poll(self):
        """Kick off the async poll worker."""
        self._do_poll()

    @work(exclusive=True, thread=True)
    def _do_poll(self):
        """Fetch agent data in a thread, then update UI."""
        import asyncio as _aio
        import sys

        async def _fetch():
            if self.direct_agents:
                agents = []
                for da in self.direct_agents:
                    name = da.get("name", f"port-{da['port']}")
                    port = da["port"]
                    agents.append({"name": name, "port": port, "model": "?", "status": "running"})
            elif self.supervisor:
                try:
                    agents = await self.supervisor.list_agents()
                except Exception:
                    agents = []
            else:
                agents = []

            tasks = [fetch_detail(a["name"], a["port"]) for a in agents]
            results = await _aio.gather(*tasks, return_exceptions=True)

            details = {}
            for result in results:
                if isinstance(result, AgentDetail):
                    details[result.name] = result

            return agents, details

        try:
            loop = _aio.new_event_loop()
            agents, details = loop.run_until_complete(_fetch())
            loop.close()
            self.details = details
            self.app.call_from_thread(self._update_table, agents)
        except Exception as e:
            print(f"[monitor poll error] {e}", file=sys.stderr)

    def _update_table(self, agents: list[dict]):
        table = self.query_one("#agent-table", AgentTable)
        table.clear()

        for a in agents:
            name = a["name"]
            d = self.details.get(name)
            s = d.status if d else None
            status = "●" if d and d.reachable else "○"

            table.add_row(
                name,
                str(a.get("port", "?")),
                status,
                str(s.active if s else "-"),
                str(s.keystones if s else "-"),
                str(s.forgiven if s else "-"),
                str(s.archived if s else "-"),
                str(s.graph_nodes if s else "-"),
                str(s.graph_edges if s else "-"),
                d.hexagram if d else "-",
                d.emotions if d else "-",
                key=name,
            )

        # Re-select if we had a selection
        if self.selected_agent and self.selected_agent in self.details:
            detail_panel = self.query_one("#detail-panel", DetailPanel)
            detail_panel.update_detail(self.details[self.selected_agent])

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        name = str(event.row_key.value)
        self.selected_agent = name
        detail_panel = self.query_one("#detail-panel", DetailPanel)
        detail_panel.update_detail(self.details.get(name))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        if event.row_key:
            name = str(event.row_key.value)
            self.selected_agent = name
            detail_panel = self.query_one("#detail-panel", DetailPanel)
            detail_panel.update_detail(self.details.get(name))

    # ── Actions ─────────────────────────────────────────────────────────

    def action_refresh(self):
        self._start_poll()

    def action_toggle_chat(self):
        chat = self.query_one("#chat-panel", ChatPanel)
        if chat.has_class("visible"):
            chat.remove_class("visible")
        else:
            if not self.selected_agent:
                self.notify("Select an agent first", severity="warning")
                return
            chat.add_class("visible")
            log = self.query_one("#chat-log", Log)
            log.write_line(f"[chat] {self.selected_agent}")
            self.query_one("#chat-input", Input).focus()

    def action_dream_selected(self):
        if not self.selected_agent:
            self.notify("Select an agent first", severity="warning")
            return
        self._do_dream(self.selected_agent)

    @work(exclusive=True, group="dream")
    async def _do_dream(self, name: str):
        d = self.details.get(name)
        if not d or not d.reachable:
            self.notify(f"{name} not reachable", severity="error")
            return
        client = FerriculaClient(f"http://localhost:{d.port}", name)
        import os
        entropy = os.urandom(64).hex()
        report = await client.offer(entropy)
        arcs = ",".join(report.active_archetypes) or "none"
        self.notify(
            f"{name}: decayed={report.decayed} "
            f"consolidated={report.consolidated} "
            f"archetypes=[{arcs}]",
            title="Dream",
        )
        # Refresh to show updated stats
        self._poll_agents()

    async def on_input_submitted(self, event: Input.Submitted):
        """Handle chat input."""
        msg = event.value.strip()
        if not msg:
            return
        event.input.value = ""

        if not self.selected_agent:
            return

        name = self.selected_agent
        d = self.details.get(name)
        if not d or not d.reachable:
            self.notify(f"{name} not reachable", severity="error")
            return

        log = self.query_one("#chat-log", Log)
        log.write_line(f"you> {msg}")

        # Check for special commands
        if msg.lower() == "status":
            if d.status:
                s = d.status
                log.write_line(
                    f"  active={s.active} keystones={s.keystones} "
                    f"edges={s.graph_edges}"
                )
            return

        if msg.lower() == "dream":
            self._do_dream(name)
            return

        # Chat via agent — need AGENT_KEY
        self._do_chat(name, d.port, msg)

    @work(exclusive=True, group="chat")
    async def _do_chat(self, name: str, port: int, message: str):
        """Send chat message to agent via LLM."""
        import os
        api_key = os.environ.get("AGENT_KEY", "")
        if not api_key:
            log = self.query_one("#chat-log", Log)
            self.call_from_thread(
                log.write_line, "  [error] AGENT_KEY not set"
            )
            return

        # Recall memories for context
        client = FerriculaClient(f"http://localhost:{port}", name)
        shivvr_url = "http://nemesis:8080"  # default shivvr endpoint

        # Look up shivvr URL from supervisor registry
        reg = self.supervisor._registry.get(name, {})
        # For now use default shivvr

        shivvr = ShivvrClient(shivvr_url)
        try:
            hits = await client.recall_text(message, shivvr, k=5)
            recalled = []
            for hit in hits:
                row = await client.get_row(hit.id)
                text = row.get("tags", {}).get("text", "")
                if text:
                    recalled.append(text)
        except Exception:
            recalled = []

        # Build prompt and call Claude
        d = self.details.get(name)
        identity = d.identity if d else {}

        memories_str = "\n".join(f"- {t}" for t in recalled[:5]) or "(none)"
        system = (
            f"You are {name}.\n"
            f"Hexagram: {identity.get('hexagram', {}).get('name', '?')}\n\n"
            f"Your relevant memories:\n{memories_str}\n\n"
            f"Respond naturally. Draw on memories if relevant."
        )

        import httpx
        try:
            async with httpx.AsyncClient() as http:
                resp = await http.post(
                    "https://api.anthropic.com/v1/messages",
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 512,
                        "system": system,
                        "messages": [{"role": "user", "content": message}],
                    },
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                reply = data["content"][0]["text"]
        except Exception as e:
            reply = f"[error] {e}"

        log = self.query_one("#chat-log", Log)
        self.call_from_thread(log.write_line, f"{name}> {reply}")

        # Remember the exchange
        try:
            exchange = f"User: {message[:80]} | Reply: {reply[:80]}"
            vec = await shivvr.embed(exchange)
            await client.remember(exchange, vec, channel="thinking")
        except Exception:
            pass


def run_monitor(agents: list[dict] | None = None):
    """Entry point for the monitor TUI.

    Args:
        agents: Optional list of {"name": ..., "port": ...} dicts for direct
                connection mode (bypasses supervisor registry).
    """
    app = MonitorApp(direct_agents=agents)
    app.run()


if __name__ == "__main__":
    run_monitor()
