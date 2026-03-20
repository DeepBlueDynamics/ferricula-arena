"""CLI entry point for ferricula-arena.

Usage:
    arena create --template agents/reader.toml --name Scholar --port 8770
    arena train --agent Scholar --dataset data/papers/ --dreams 5
    arena audit --agent Scholar
    arena chat --agent Scholar
    arena list
    arena stop --agent Scholar
    arena resume --agent Scholar
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ARENA_ROOT = Path(__file__).resolve().parent.parent


def _get_supervisor():
    from .supervisor import Supervisor
    return Supervisor()


# ── Subcommands ─────────────────────────────────────────────────────────

async def cmd_create(args):
    """Create and start an agent from a TOML template."""
    sup = _get_supervisor()

    template = args.template
    # Resolve relative to arena root if not absolute
    if not Path(template).is_absolute():
        candidate = ARENA_ROOT / template
        if candidate.exists():
            template = str(candidate)

    await sup.create_agent(
        template,
        name=args.name,
        port=args.port,
    )


async def cmd_train(args):
    """Train an agent on a dataset directory."""
    from .trainer import train as run_train

    sup = _get_supervisor()
    agent = await sup.resume_agent(args.agent)

    dataset = args.dataset
    if not Path(dataset).is_absolute():
        candidate = ARENA_ROOT / dataset
        if candidate.exists():
            dataset = str(candidate)

    report = await run_train(agent, dataset, dreams=args.dreams)

    # Run advocate audit after training if configured
    if agent.config.advocate.review_interval == "after_training":
        from .advocate import audit, apply_recommendations
        audit_report = await audit(agent)
        await apply_recommendations(agent, audit_report)


async def cmd_audit(args):
    """Run advocate audit on an agent."""
    from .advocate import audit, apply_recommendations

    sup = _get_supervisor()
    agent = await sup.resume_agent(args.agent)

    dataset_terms = None
    if args.terms:
        dataset_terms = [t.strip() for t in args.terms.split(",")]

    report = await audit(agent, dataset_terms=dataset_terms)

    if args.apply:
        await apply_recommendations(
            agent, report,
            auto_promote=True,
            auto_demote=args.demote,
        )


async def cmd_chat(args):
    """Interactive chat with an agent."""
    sup = _get_supervisor()
    agent = await sup.resume_agent(args.agent)

    identity = agent.state.identity or {}
    hex_name = identity.get("hexagram", {}).get("name", "")
    print(f"[chat] {agent.name} ({hex_name})")
    print(f"  model: {agent.config.model}")
    print(f"  type 'quit' to exit, 'status' for stats, 'dream' to trigger dream\n")

    while True:
        try:
            user_input = input(f"you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[bye]")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("[bye]")
            break
        if user_input.lower() == "status":
            status = await agent.status()
            print(f"  active={status.active} keystones={status.keystones} "
                  f"edges={status.graph_edges} dreams={agent.state.total_dreams}")
            continue
        if user_input.lower() == "dream":
            report = await agent.offer()
            arcs = ",".join(report.active_archetypes) or "none"
            print(f"  ~dream~ decayed={report.decayed} "
                  f"consolidated={report.consolidated} "
                  f"archetypes=[{arcs}]")
            continue

        try:
            reply = await agent.chat(user_input)
            print(f"\n{agent.name}> {reply}\n")
        except Exception as e:
            print(f"  [error] {e}")


async def cmd_list(args):
    """List all registered agents."""
    sup = _get_supervisor()
    agents = await sup.list_agents()

    if not agents:
        print("no agents registered")
        return

    for a in agents:
        status_icon = {"running": "+", "stopped": "-", "unknown": "?"}.get(
            a["status"], "?"
        )
        line = f"  [{status_icon}] {a['name']} :{a['port']} ({a['model']})"
        if a["status"] == "running":
            line += (f" — {a.get('active_memories', '?')} active"
                     f", {a.get('keystones', '?')} keystones"
                     f", {a.get('graph_edges', '?')} edges")
        print(line)


async def cmd_stop(args):
    """Stop an agent's container."""
    sup = _get_supervisor()
    # Need to reconnect to agent before stopping
    if args.agent not in sup.agents and args.agent in sup._registry:
        reg = sup._registry[args.agent]
        from .agent import Agent
        from .config import AgentConfig
        config = AgentConfig(name=args.agent)
        agent = Agent(config, port=reg["port"], name=args.agent)
        agent.state.container_name = reg.get("container_name")
        sup.agents[args.agent] = agent
    await sup.stop_agent(args.agent)


async def cmd_resume(args):
    """Resume a stopped agent."""
    sup = _get_supervisor()
    await sup.resume_agent(args.agent)


async def cmd_dream(args):
    """Run dream cycles on an agent or all agents."""
    sup = _get_supervisor()
    if args.agent:
        agent = await sup.resume_agent(args.agent)
        for i in range(args.cycles):
            report = await agent.offer()
            arcs = ",".join(report.active_archetypes) or "none"
            print(f"  [{i+1}/{args.cycles}] decayed={report.decayed} "
                  f"consolidated={report.consolidated} "
                  f"edges={report.edges_created} "
                  f"archetypes=[{arcs}]")
    else:
        # Dream all registered + running agents
        for name in list(sup._registry.keys()):
            try:
                agent = await sup.resume_agent(name)
                for _ in range(args.cycles):
                    await agent.offer()
                print(f"  {name}: {args.cycles} dreams")
            except Exception as e:
                print(f"  {name}: skipped ({e})")


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="arena",
        description="ferricula-arena — agent runner SDK",
    )
    sub = parser.add_subparsers(dest="command")

    # create
    p = sub.add_parser("create", help="Create an agent from template")
    p.add_argument("--template", "-t", required=True,
                   help="Path to agent TOML template")
    p.add_argument("--name", "-n", help="Agent name (overrides template)")
    p.add_argument("--port", "-p", type=int, default=0,
                   help="Port for ferricula container")

    # train
    p = sub.add_parser("train", help="Train agent on a dataset")
    p.add_argument("--agent", "-a", required=True, help="Agent name")
    p.add_argument("--dataset", "-d", required=True,
                   help="Path to dataset directory")
    p.add_argument("--dreams", type=int, default=5,
                   help="Dream cycles after training (default: 5)")

    # audit
    p = sub.add_parser("audit", help="Run advocate audit")
    p.add_argument("--agent", "-a", required=True, help="Agent name")
    p.add_argument("--terms", help="Comma-separated terms for gap analysis")
    p.add_argument("--apply", action="store_true",
                   help="Apply recommendations (promotions)")
    p.add_argument("--demote", action="store_true",
                   help="Also apply demotions (requires --apply)")

    # chat
    p = sub.add_parser("chat", help="Interactive chat with an agent")
    p.add_argument("--agent", "-a", required=True, help="Agent name")

    # list
    sub.add_parser("list", help="List all agents")

    # stop
    p = sub.add_parser("stop", help="Stop an agent")
    p.add_argument("--agent", "-a", required=True, help="Agent name")

    # resume
    p = sub.add_parser("resume", help="Resume a stopped agent")
    p.add_argument("--agent", "-a", required=True, help="Agent name")

    # dream
    p = sub.add_parser("dream", help="Run dream cycles")
    p.add_argument("--agent", "-a", help="Agent name (all if omitted)")
    p.add_argument("--cycles", "-c", type=int, default=3,
                   help="Number of dream cycles (default: 3)")

    # monitor
    sub.add_parser("monitor", help="Live TUI dashboard")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Monitor runs its own event loop (Textual), not asyncio.run
    if args.command == "monitor":
        from .monitor import run_monitor
        run_monitor()
        return

    dispatch = {
        "create": cmd_create,
        "train": cmd_train,
        "audit": cmd_audit,
        "chat": cmd_chat,
        "list": cmd_list,
        "stop": cmd_stop,
        "resume": cmd_resume,
        "dream": cmd_dream,
    }

    asyncio.run(dispatch[args.command](args))


if __name__ == "__main__":
    main()
