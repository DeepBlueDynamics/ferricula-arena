"""Memory advocate — audits keystones, challenges fidelity, identifies gaps.

The advocate runs after training (or on schedule) and:
  1. Reviews keystones — are they still relevant? Should any be demoted?
  2. Challenges memory quality — recall random memories, check coherence
  3. Identifies gaps — what important concepts are missing?
  4. Reports recommendations (promote, demote, remember more)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .agent import Agent
from .clients import InspectResult


@dataclass
class AuditRecommendation:
    action: str  # "promote", "demote", "gap"
    memory_id: Optional[int] = None
    reason: str = ""
    term: Optional[str] = None  # for gap recommendations


@dataclass
class AuditReport:
    agent_name: str = ""
    keystones_reviewed: int = 0
    keystones_healthy: int = 0
    keystones_degraded: int = 0
    memories_challenged: int = 0
    memories_coherent: int = 0
    gaps: list[str] = field(default_factory=list)
    recommendations: list[AuditRecommendation] = field(default_factory=list)

    def summary(self) -> str:
        promotes = [r for r in self.recommendations if r.action == "promote"]
        demotes = [r for r in self.recommendations if r.action == "demote"]
        gaps = [r for r in self.recommendations if r.action == "gap"]
        lines = [
            f"[audit] {self.agent_name}",
            f"  keystones: {self.keystones_healthy}/{self.keystones_reviewed} healthy"
            f" ({self.keystones_degraded} degraded)",
            f"  challenge: {self.memories_coherent}/{self.memories_challenged} coherent",
        ]
        if promotes:
            ids = [str(r.memory_id) for r in promotes]
            lines.append(f"  PROMOTE: {len(promotes)} memories ({', '.join(ids)})")
        if demotes:
            ids = [str(r.memory_id) for r in demotes]
            lines.append(f"  DEMOTE:  {len(demotes)} keystones ({', '.join(ids)})")
        if gaps:
            terms = [r.term for r in gaps if r.term]
            lines.append(f"  GAPS:    {terms}")
        return "\n".join(lines)


async def audit(agent: Agent, *,
                dataset_terms: Optional[list[str]] = None,
                progress: bool = True) -> AuditReport:
    """Run a full memory quality audit on an agent.

    Args:
        agent: The agent to audit.
        dataset_terms: Optional list of important terms from the training data.
            Used for gap analysis.
        progress: Print progress to stdout.
    """
    config = agent.config.advocate
    report = AuditReport(agent_name=agent.name)

    if progress:
        print(f"[audit] {agent.name}")

    # Get current status
    status = await agent.status()

    # 1. KEYSTONE REVIEW — inspect all memories, find keystones, check fidelity
    if progress:
        print(f"  [keystones] scanning {status.memories} memories...", end="")

    keystone_ids = []
    high_fidelity_non_keystones = []

    # Scan all memory IDs to find keystones
    for mid in range(1, agent.ferricula._next_id):
        try:
            info = await agent.ferricula.inspect(mid)
        except Exception:
            continue

        if info.state != "Active":
            continue

        if info.keystone:
            keystone_ids.append(mid)
            report.keystones_reviewed += 1
            if info.fidelity >= config.min_keystone_fidelity:
                report.keystones_healthy += 1
            else:
                report.keystones_degraded += 1
                # Keystone with degraded fidelity — consider demotion
                if info.fidelity < 0.8 and info.recalls == 0:
                    report.recommendations.append(AuditRecommendation(
                        action="demote",
                        memory_id=mid,
                        reason=f"fidelity={info.fidelity:.3f}, 0 recalls",
                    ))
        else:
            # Non-keystone with high fidelity and recall count → promotion candidate
            if (info.fidelity >= config.min_keystone_fidelity
                    and info.recalls >= 3):
                high_fidelity_non_keystones.append((mid, info))

    if progress:
        print(f" {report.keystones_reviewed} keystones found")

    # Promotion candidates
    for mid, info in high_fidelity_non_keystones:
        report.recommendations.append(AuditRecommendation(
            action="promote",
            memory_id=mid,
            reason=f"fidelity={info.fidelity:.3f}, recalls={info.recalls}",
        ))

    # 2. RANDOM CHALLENGE — recall random memories, check they're coherent
    challenge_count = max(1, int(status.active * config.challenge_rate))
    if progress:
        print(f"  [challenge] testing {challenge_count} random memories...", end="")

    all_ids = list(range(1, agent.ferricula._next_id))
    sample = random.sample(all_ids, min(challenge_count, len(all_ids)))

    for mid in sample:
        try:
            info = await agent.ferricula.inspect(mid)
            if info.state != "Active":
                continue
            report.memories_challenged += 1

            # A memory is "coherent" if it has reasonable fidelity
            # and its text is retrievable
            row = await agent.ferricula.get_row(mid)
            text = row.get("tags", {}).get("text", "")
            if text and info.fidelity > 0.3:
                report.memories_coherent += 1
        except Exception:
            continue

    if progress:
        print(f" {report.memories_coherent}/{report.memories_challenged} coherent")

    # 3. GAP ANALYSIS — compare agent's term index against dataset terms
    if dataset_terms and config.gap_detection:
        if progress:
            print(f"  [gaps] checking {len(dataset_terms)} terms...", end="")

        # Get the agent's term index
        try:
            terms_text = await agent.ferricula.terms()
            agent_terms = set(terms_text.lower().split())
        except Exception:
            agent_terms = set()

        for term in dataset_terms:
            if term.lower() not in agent_terms:
                # Try a search to be sure
                try:
                    search_result = await agent.ferricula.search(term)
                    if "no results" in search_result.lower() or not search_result.strip():
                        report.gaps.append(term)
                        report.recommendations.append(AuditRecommendation(
                            action="gap",
                            term=term,
                            reason=f"term '{term}' not found in memory",
                        ))
                except Exception:
                    report.gaps.append(term)

        if progress:
            print(f" {len(report.gaps)} gaps found")

    # Print summary
    if progress:
        print(report.summary())

    return report


async def apply_recommendations(agent: Agent, report: AuditReport, *,
                                auto_promote: bool = True,
                                auto_demote: bool = False):
    """Apply audit recommendations to an agent.

    Promotions are applied automatically by default.
    Demotions require explicit opt-in.
    """
    for rec in report.recommendations:
        if rec.action == "promote" and auto_promote and rec.memory_id:
            await agent.ferricula.keystone(rec.memory_id)
            print(f"  [promoted] memory {rec.memory_id}: {rec.reason}")
        elif rec.action == "demote" and auto_demote and rec.memory_id:
            await agent.ferricula.keystone(rec.memory_id)  # toggle off
            print(f"  [demoted] keystone {rec.memory_id}: {rec.reason}")
