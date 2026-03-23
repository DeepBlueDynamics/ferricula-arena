"""Tests for arena.clients — response parsing from ferricula server output."""

import json
import unittest

from arena.clients import (
    DreamReport,
    InspectResult,
    RecallHit,
    StatusResult,
    _unwrap,
    parse_dream_report,
    parse_inspect,
    parse_recall,
    parse_remember_id,
    parse_status,
)


# ── Sample server output ─────────────────────────────────────────────────

DREAM_TEXT = (
    '{"result": "dream: ticks=1 decayed=5 forgiven=2 archived=0 '
    'consolidated=1 pruned=0 ghost_echoes=0 keystones_reviewed=3 '
    'edges_created=2 keystones_promoted=1 '
    'active_archetypes=[Intuition,Fortune,Ethics]"}'
)

INSPECT_TEXT = (
    '{"result": "memory id=42:\\n  state=Active\\n  fidelity=0.9234\\n'
    '  decay_alpha=0.01000 (effective=0.00870)\\n  keystone=true\\n'
    '  recalls=7\\n  consolidation_depth=2\\n  importance=0.85\\n'
    '  emotion=curiosity/trust\\n  provenance=Ingested\\n  age=3600s\\n'
    '  staleness=300s\\n  graph: degree=3 neighbors=[1, 5, 12]"}'
)

STATUS_TEXT = (
    '{"result": "rows=150 | memories=148 | active=120 forgiven=20 '
    'archived=8 | keystones=15 | 145 nodes 89 edges"}'
)

RECALL_TEXT = (
    '{"result": "  id=42 fidelity=0.92 recalls=7\\n'
    '  id=17 fidelity=0.88 recalls=3"}'
)

REMEMBER_TEXT = '{"result": "remembered id=42 channel=hearing alpha=0.010"}'


# ── _unwrap ───────────────────────────────────────────────────────────────

class TestUnwrap(unittest.TestCase):

    def test_unwrap_result_field(self):
        raw = '{"result": "hello world"}'
        self.assertEqual(_unwrap(raw), "hello world")

    def test_unwrap_error_field(self):
        raw = '{"error": "something broke"}'
        self.assertIn("error", _unwrap(raw))
        self.assertIn("something broke", _unwrap(raw))

    def test_unwrap_plain_text(self):
        raw = "not json at all"
        self.assertEqual(_unwrap(raw), "not json at all")

    def test_unwrap_no_result_key(self):
        raw = '{"other": "value"}'
        self.assertEqual(_unwrap(raw), raw)

    def test_unwrap_empty_string(self):
        self.assertEqual(_unwrap(""), "")

    def test_unwrap_nested_json(self):
        raw = json.dumps({"result": "id=1 state=Active"})
        self.assertEqual(_unwrap(raw), "id=1 state=Active")


# ── parse_dream_report ────────────────────────────────────────────────────

class TestParseDreamReport(unittest.TestCase):

    def setUp(self):
        self.report = parse_dream_report(DREAM_TEXT)

    def test_ticks(self):
        self.assertEqual(self.report.ticks, 1)

    def test_decayed(self):
        self.assertEqual(self.report.decayed, 5)

    def test_forgiven(self):
        self.assertEqual(self.report.forgiven, 2)

    def test_archived(self):
        self.assertEqual(self.report.archived, 0)

    def test_consolidated(self):
        self.assertEqual(self.report.consolidated, 1)

    def test_pruned(self):
        self.assertEqual(self.report.pruned, 0)

    def test_ghost_echoes(self):
        self.assertEqual(self.report.ghost_echoes, 0)

    def test_keystones_reviewed(self):
        self.assertEqual(self.report.keystones_reviewed, 3)

    def test_edges_created(self):
        self.assertEqual(self.report.edges_created, 2)

    def test_keystones_promoted(self):
        self.assertEqual(self.report.keystones_promoted, 1)

    def test_active_archetypes(self):
        self.assertEqual(self.report.active_archetypes, ["Intuition", "Fortune", "Ethics"])

    def test_empty_archetypes(self):
        text = '{"result": "dream: ticks=1 active_archetypes=[]"}'
        report = parse_dream_report(text)
        self.assertEqual(report.active_archetypes, [])

    def test_plain_text_input(self):
        text = "dream: ticks=3 decayed=10 consolidated=2 active_archetypes=[Fortune]"
        report = parse_dream_report(text)
        self.assertEqual(report.ticks, 3)
        self.assertEqual(report.decayed, 10)
        self.assertEqual(report.consolidated, 2)
        self.assertEqual(report.active_archetypes, ["Fortune"])


# ── parse_recall ──────────────────────────────────────────────────────────

class TestParseRecall(unittest.TestCase):

    def setUp(self):
        self.hits = parse_recall(RECALL_TEXT)

    def test_hit_count(self):
        self.assertEqual(len(self.hits), 2)

    def test_first_hit(self):
        self.assertEqual(self.hits[0].id, 42)
        self.assertAlmostEqual(self.hits[0].fidelity, 0.92, places=2)
        self.assertEqual(self.hits[0].recalls, 7)

    def test_second_hit(self):
        self.assertEqual(self.hits[1].id, 17)
        self.assertAlmostEqual(self.hits[1].fidelity, 0.88, places=2)
        self.assertEqual(self.hits[1].recalls, 3)

    def test_empty_recall(self):
        text = '{"result": "no results"}'
        hits = parse_recall(text)
        self.assertEqual(hits, [])

    def test_single_hit(self):
        text = '{"result": "  id=99 fidelity=1.00 recalls=0"}'
        hits = parse_recall(text)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].id, 99)
        self.assertAlmostEqual(hits[0].fidelity, 1.0, places=2)

    def test_fallback_id_only(self):
        """Fallback: parse id= when fidelity/recalls are missing."""
        text = '{"result": "id=5 id=10"}'
        hits = parse_recall(text)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].id, 5)
        self.assertEqual(hits[1].id, 10)


# ── parse_inspect ─────────────────────────────────────────────────────────

class TestParseInspect(unittest.TestCase):

    def setUp(self):
        self.result = parse_inspect(INSPECT_TEXT)

    def test_id(self):
        self.assertEqual(self.result.id, 42)

    def test_state(self):
        self.assertEqual(self.result.state, "Active")

    def test_fidelity(self):
        self.assertAlmostEqual(self.result.fidelity, 0.9234, places=4)

    def test_decay_alpha(self):
        self.assertAlmostEqual(self.result.decay_alpha, 0.01, places=3)

    def test_effective_alpha(self):
        self.assertAlmostEqual(self.result.effective_alpha, 0.0087, places=4)

    def test_keystone(self):
        self.assertTrue(self.result.keystone)

    def test_recalls(self):
        self.assertEqual(self.result.recalls, 7)

    def test_consolidation_depth(self):
        self.assertEqual(self.result.consolidation_depth, 2)

    def test_importance(self):
        self.assertAlmostEqual(self.result.importance, 0.85, places=2)

    def test_emotion(self):
        self.assertEqual(self.result.emotion, "curiosity/trust")

    def test_degree(self):
        self.assertEqual(self.result.degree, 3)

    def test_keystone_false(self):
        text = '{"result": "memory id=1:\\n  keystone=false"}'
        result = parse_inspect(text)
        self.assertFalse(result.keystone)

    def test_forgiven_state(self):
        text = '{"result": "memory id=7:\\n  state=Forgiven\\n  fidelity=0.1000"}'
        result = parse_inspect(text)
        self.assertEqual(result.state, "Forgiven")
        self.assertAlmostEqual(result.fidelity, 0.1, places=1)


# ── parse_status ──────────────────────────────────────────────────────────

class TestParseStatus(unittest.TestCase):

    def setUp(self):
        self.result = parse_status(STATUS_TEXT)

    def test_rows(self):
        self.assertEqual(self.result.rows, 150)

    def test_memories(self):
        self.assertEqual(self.result.memories, 148)

    def test_active(self):
        self.assertEqual(self.result.active, 120)

    def test_forgiven(self):
        self.assertEqual(self.result.forgiven, 20)

    def test_archived(self):
        self.assertEqual(self.result.archived, 8)

    def test_keystones(self):
        self.assertEqual(self.result.keystones, 15)

    def test_graph_nodes(self):
        self.assertEqual(self.result.graph_nodes, 145)

    def test_graph_edges(self):
        self.assertEqual(self.result.graph_edges, 89)

    def test_empty_status(self):
        text = '{"result": "rows=0 | memories=0 | active=0 forgiven=0 archived=0 | keystones=0 | 0 nodes 0 edges"}'
        result = parse_status(text)
        self.assertEqual(result.rows, 0)
        self.assertEqual(result.memories, 0)
        self.assertEqual(result.graph_nodes, 0)


# ── parse_remember_id ─────────────────────────────────────────────────────

class TestParseRememberId(unittest.TestCase):

    def test_standard_output(self):
        self.assertEqual(parse_remember_id(REMEMBER_TEXT), 42)

    def test_no_id(self):
        text = '{"result": "error: failed to remember"}'
        self.assertIsNone(parse_remember_id(text))

    def test_plain_text(self):
        text = "remembered id=99 channel=seeing"
        self.assertEqual(parse_remember_id(text), 99)

    def test_large_id(self):
        text = '{"result": "remembered id=123456 channel=hearing alpha=0.003"}'
        self.assertEqual(parse_remember_id(text), 123456)


if __name__ == "__main__":
    unittest.main()
