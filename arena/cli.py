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

    report = await run_train(agent, dataset, dreams=args.dreams, progress=True)

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
    import os
    from .agent import Agent
    from .clients import ChonkClient, FerriculaClient
    from .config import AgentConfig, PersonalityConfig, MemoryConfig

    if args.port:
        # Direct connection mode — no supervisor needed
        url = f"http://localhost:{args.port}"
        chonk_url = args.chonk or os.environ.get("CHONK_URL", "http://nemesis:8080")
        ferricula = FerriculaClient(url, args.agent or "agent")
        chonk = ChonkClient(chonk_url)

        if not await ferricula.available():
            print(f"[error] ferricula not reachable at {url}")
            return

        identity = await ferricula.identity()
        name = identity.get("name", args.agent or "agent")
        hex_name = identity.get("hexagram", {}).get("name", "")
        hex_num = identity.get("hexagram", {}).get("number", "")
        zodiac = identity.get("horoscope", {}).get("sign_name", "")
        primary_emo = identity.get("primary_emotion", "")
        secondary_emo = identity.get("secondary_emotion", "")

        # Build a minimal Agent with the right config
        config = AgentConfig(
            name=name,
            role=args.role or f"Character agent — {name}",
            model=args.model or "claude-sonnet-4-6",
            personality=PersonalityConfig(
                trait="In character",
                voice="Speak as the character naturally would",
                focus=[],
            ),
            memory=MemoryConfig(chonk_url=chonk_url),
        )
        agent = Agent(config, port=args.port, name=name)
        agent.ferricula = ferricula
        agent.chonk = chonk
        agent.state.identity = identity
    else:
        sup = _get_supervisor()
        agent = await sup.resume_agent(args.agent)
        identity = agent.state.identity or {}
        name = agent.name
        hex_name = identity.get("hexagram", {}).get("name", "")
        hex_num = identity.get("hexagram", {}).get("number", "")
        zodiac = identity.get("horoscope", {}).get("sign_name", "")
        primary_emo = identity.get("primary_emotion", "")
        secondary_emo = identity.get("secondary_emotion", "")

    status = await agent.ferricula.status()
    print(f"\n  {name}")
    if hex_name:
        print(f"  Hexagram #{hex_num} {hex_name} | {zodiac} | {primary_emo}/{secondary_emo}")
    print(f"  {status.active} active memories, {status.keystones} keystones, {status.graph_edges} edges")
    print(f"  model: {agent._model}")
    print(f"  autonomous thinking: on")
    print(f"  type 'quit' to exit, 'status' for stats, 'dream' to trigger dream\n")

    # Start autonomous thinking loop in background
    from .autonomous import autonomous_loop
    stop_event = asyncio.Event()

    def interrupt_print(text):
        """Print agent's spontaneous thought to terminal."""
        sys.stdout.write(text)
        sys.stdout.flush()

    auto_task = asyncio.create_task(
        autonomous_loop(
            ferricula=agent.ferricula,
            chonk=agent.chonk,
            name=name,
            api_key=agent._api_key,
            model=agent._model,
            identity=identity,
            interrupt_callback=interrupt_print,
            stop_event=stop_event,
        )
    )

    # Input runs in a thread, chat stays async.
    # Ctrl-c: thread catches KeyboardInterrupt, puts sentinel on queue.
    import queue
    import threading

    input_q = queue.Queue()
    _quit = object()
    _interrupt = object()

    def _input_thread():
        """Dedicated thread for blocking input. Never touches asyncio."""
        while True:
            try:
                line = input("you> ").strip()
                input_q.put(line)
            except KeyboardInterrupt:
                input_q.put(_interrupt)
            except EOFError:
                # Only quit on real EOF, not transient errors
                import time as _t
                _t.sleep(0.1)
                input_q.put(_interrupt)  # treat as ctrl-c, not quit

    t = threading.Thread(target=_input_thread, daemon=True)
    t.start()

    try:
        while True:
            # Poll the queue so autonomous loop can run between checks
            user_input = None
            while user_input is None:
                try:
                    user_input = input_q.get(timeout=0.2)
                except queue.Empty:
                    # Let asyncio tasks run (autonomous thinking)
                    await asyncio.sleep(0)
                    continue

            if user_input is _quit:
                print("[bye]")
                break

            if user_input is _interrupt:
                # Ctrl-c hit — ask to quit
                print()
                print("  quit? (y/n) ", end="", flush=True)
                try:
                    confirm = input_q.get(timeout=10)
                except queue.Empty:
                    confirm = "y"
                if confirm is _interrupt or confirm is _quit:
                    print("[bye]")
                    break
                if isinstance(confirm, str) and confirm.lower() in ("y", "yes", ""):
                    print("[bye]")
                    break
                continue

            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("[bye]")
                break
            if user_input.lower() == "status":
                try:
                    s = await agent.ferricula.status()
                    print(f"  active={s.active} keystones={s.keystones} "
                          f"edges={s.graph_edges} dreams={agent.state.total_dreams}")
                except Exception as e:
                    print(f"  [error] {e}")
                continue
            if user_input.lower() == "dream":
                try:
                    report = await agent.offer()
                    arcs = ",".join(report.active_archetypes) or "none"
                    print(f"  ~dream~ decayed={report.decayed} "
                          f"consolidated={report.consolidated} "
                          f"archetypes=[{arcs}]")
                except Exception as e:
                    print(f"  [error] {e}")
                continue

            try:
                reply = await agent.chat(user_input)
                print(f"\n{name}> {reply}\n")
            except Exception as e:
                print(f"  [error] {e}")
    except BaseException:
        pass
    finally:
        stop_event.set()
        try:
            auto_task.cancel()
        except BaseException:
            pass


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
    p.add_argument("--agent", "-a", help="Agent name (required unless --port)")
    p.add_argument("--port", "-p", type=int, default=0,
                   help="Connect directly to ferricula on this port")
    p.add_argument("--chonk", help="Chonk/shivvr URL (default: CHONK_URL env or nemesis:8080)")
    p.add_argument("--model", "-m", help="LLM model (default: claude-sonnet-4-6)")
    p.add_argument("--role", help="Override agent role/system prompt")

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
    p = sub.add_parser("monitor", help="Live TUI dashboard")
    p.add_argument("--port", "-p", type=int, action="append", default=[],
                   help="Connect directly to ferricula on this port (repeatable)")
    p.add_argument("--agent", "-a", action="append", default=[],
                   help="Agent name for corresponding --port (optional)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Monitor runs its own event loop (Textual), not asyncio.run
    if args.command == "monitor":
        from .monitor import run_monitor
        direct = None
        if args.port:
            direct = []
            for i, port in enumerate(args.port):
                name = args.agent[i] if i < len(args.agent) else f"port-{port}"
                direct.append({"name": name, "port": port})
        run_monitor(agents=direct)
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

    if args.command == "chat":
        # Chat needs special signal handling — Python's asyncio.run
        # converts SIGINT to CancelledError which bypasses our catch.
        # Use a loop with custom signal handling instead.
        import signal
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Ignore SIGINT at the asyncio level — let the chat REPL handle it
            if hasattr(signal, 'SIGINT'):
                loop.add_signal_handler(signal.SIGINT, lambda: None)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler
        # Suppress "Task was destroyed" warnings
        loop.set_exception_handler(lambda l, c: None)
        try:
            loop.run_until_complete(dispatch["chat"](args))
        except BaseException:
            print("\n[bye]")
        finally:
            try:
                loop.close()
            except BaseException:
                pass
    else:
        try:
            asyncio.run(dispatch[args.command](args))
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n[bye]")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
