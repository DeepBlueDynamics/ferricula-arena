"""Dataset trainer — feeds documents, classifies keystones, fast-forwards dreams.

Training flow:
  1. SCAN    — find .txt, .md, .pdf files in dataset directory
  2. CHUNK   — send each file to shivvr for chunking + embedding
  3. CLASSIFY — match chunks against keystone_patterns from agent template
  4. INGEST  — POST to ferricula /remember with channel/emotion/importance
  5. SEED    — connect related memories (co-occurrence, semantic)
  6. DREAM   — run N dream cycles via /offer with entropy
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .agent import Agent
from .clients import DreamReport


@dataclass
class ChunkResult:
    text: str
    embedding: list[float]
    source_file: str
    keystone: bool = False
    importance: float = 0.0
    pattern_matches: list[str] = field(default_factory=list)


@dataclass
class TrainReport:
    files_scanned: int = 0
    chunks_total: int = 0
    keystones_found: int = 0
    memories_ingested: int = 0
    edges_seeded: int = 0
    dreams_run: int = 0
    dream_reports: list[DreamReport] = field(default_factory=list)


def _scan_dataset(dataset_dir: str | Path) -> list[Path]:
    """Find all trainable files in the dataset directory."""
    root = Path(dataset_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {root}")
    extensions = {".txt", ".md", ".pdf"}
    files = sorted(
        p for p in root.rglob("*")
        if p.suffix.lower() in extensions and p.is_file()
    )
    return files


def _classify_keystone(text: str, patterns: list[str],
                       focus: list[str]) -> tuple[bool, float, list[str]]:
    """Classify whether a chunk should be a keystone.

    A chunk becomes a keystone if:
      - It matches 3+ patterns, OR
      - It matches 2+ patterns AND mentions 2+ focus terms

    Returns (is_keystone, importance, matched_patterns).
    """
    matched = []
    text_lower = text.lower()
    for pat in patterns:
        if re.search(pat, text_lower):
            matched.append(pat)

    focus_hits = sum(1 for f in focus if f.lower() in text_lower)

    is_keystone = (len(matched) >= 3 or
                   (len(matched) >= 2 and focus_hits >= 2))

    # Importance: 0.0-1.0 based on pattern density
    importance = min(1.0, (len(matched) * 0.25) + (focus_hits * 0.15))

    return is_keystone, importance, matched


async def train(agent: Agent, dataset_dir: str | Path, *,
                dreams: int = 5,
                progress: bool = True) -> TrainReport:
    """Train an agent on a dataset directory.

    Chunks documents, classifies keystones, ingests into ferricula,
    seeds the knowledge graph, and fast-forwards dream cycles.
    """
    report = TrainReport()
    config = agent.config
    patterns = config.training.keystone_patterns
    focus = config.personality.focus

    # 1. SCAN
    files = _scan_dataset(dataset_dir)
    report.files_scanned = len(files)
    if progress:
        print(f"[scan] {len(files)} files in {dataset_dir}")

    if not files:
        print("  no trainable files found")
        return report

    # 2-4. CHUNK + CLASSIFY + INGEST (per file)
    all_chunk_ids: list[int] = []  # for graph seeding
    file_chunk_ids: dict[str, list[int]] = {}  # file -> memory IDs

    for i, fpath in enumerate(files):
        if progress:
            print(f"[{i+1}/{len(files)}] {fpath.name}", end="")
            sys.stdout.flush()

        # Read file — PDFs need special handling
        if fpath.suffix.lower() == ".pdf":
            try:
                import subprocess as _sp
                result = _sp.run(
                    ["python", "-c", f"import fitz; doc=fitz.open(r'{fpath}'); print('\\n'.join(p.get_text() for p in doc))"],
                    capture_output=True, text=True, timeout=60,
                )
                text = result.stdout if result.returncode == 0 else ""
                if not text.strip():
                    # Fallback: read as binary, let shivvr handle it
                    text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = fpath.read_text(encoding="utf-8", errors="replace")
        else:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            if progress:
                print(" (empty, skipped)")
            continue

        # Chunk via shivvr
        try:
            chunks = await agent.chonk.chunk_and_embed(text)
        except Exception as e:
            if progress:
                print(f" ERROR chunking: {e}")
            continue

        if progress:
            print(f" → {len(chunks)} chunks", end="")

        file_ids: list[int] = []
        keystones_in_file = 0

        for chunk in chunks:
            report.chunks_total += 1

            # Classify
            is_ks, importance, matched = _classify_keystone(
                chunk["text"], patterns, focus,
            )
            if is_ks:
                report.keystones_found += 1
                keystones_in_file += 1

            # Ingest
            alpha = (config.training.decay_alpha_keystone if is_ks
                     else config.training.decay_alpha_normal)
            mid = await agent.ferricula.remember(
                chunk["text"],
                chunk["embedding"],
                channel="hearing",
                decay_alpha=alpha,
                keystone=is_ks,
                importance=importance,
            )
            report.memories_ingested += 1
            file_ids.append(mid)
            all_chunk_ids.append(mid)

        file_chunk_ids[str(fpath)] = file_ids
        if progress:
            ks_str = f", {keystones_in_file} keystones" if keystones_in_file else ""
            print(f", {len(file_ids)} ingested{ks_str}")

    # 5. SEED GRAPH — connect consecutive chunks within each file
    if progress:
        print(f"[graph] seeding co-occurrence edges", end="")
    for fpath_str, ids in file_chunk_ids.items():
        if len(ids) < 2:
            continue
        for i in range(len(ids) - 1):
            await agent.ferricula.connect(
                ids[i], ids[i + 1],
                label="co-occurrence",
                kind="semantic",
            )
            report.edges_seeded += 1
    if progress:
        print(f" → {report.edges_seeded} edges")

    # 6. FAST-FORWARD DREAMS
    if dreams > 0:
        if progress:
            print(f"[dream] fast-forwarding {dreams} cycles", end="")
            sys.stdout.flush()
        for i in range(dreams):
            entropy_hex = os.urandom(64).hex()
            dream_report = await agent.ferricula.offer(entropy_hex)
            report.dream_reports.append(dream_report)
            report.dreams_run += 1
            agent.state.total_dreams += 1
            if progress:
                sys.stdout.write("~")
                sys.stdout.flush()
        if progress:
            last = report.dream_reports[-1] if report.dream_reports else DreamReport()
            arcs = ",".join(last.active_archetypes) or "none"
            print(f"\n  last dream: decayed={last.decayed} "
                  f"consolidated={last.consolidated} "
                  f"edges={last.edges_created} "
                  f"promoted={last.keystones_promoted} "
                  f"archetypes=[{arcs}]")

    # Summary
    if progress:
        print(f"\n[done] {report.memories_ingested} memories, "
              f"{report.keystones_found} keystones, "
              f"{report.edges_seeded} edges, "
              f"{report.dreams_run} dreams")

    return report
