"""Tests for arena.config — TOML loading and default values."""

import tempfile
import unittest
from pathlib import Path

from arena.config import (
    AgentConfig,
    AdvocateConfig,
    GraphConfig,
    MemoryConfig,
    PersonalityConfig,
    TrainingConfig,
    load_config,
)


FULL_TOML = """\
[agent]
name = "TestBot"
role = "Unit test agent"
model = "claude-sonnet-4-6"

[personality]
trait = "Curious"
voice = "Warm and exploratory"
focus = ["physics", "philosophy"]
emotions = { primary = "curiosity", secondary = "joy" }

[memory]
chonk_url = "http://localhost:8080"
radio_url = "http://localhost:9090"
clock_tick_secs = 3600
dream_threshold_bytes = 32

[training]
keystone_patterns = ["theorem", "definition", "axiom"]
decay_alpha_keystone = 0.002
decay_alpha_normal = 0.015
dreams_per_chapter = 5
chunk_size = 256

[advocate]
review_interval = "daily"
min_keystone_fidelity = 0.90
gap_detection = false
challenge_rate = 0.2
source_verification = true

[graph]
auto_connect = true
edge_discovery = true
causal_labels = ["caused", "preceded", "triggered"]
semantic_labels = ["related", "similar", "analogous"]

[tools]
enabled = ["remember", "recall", "dream"]
"""


MINIMAL_TOML = """\
[agent]
name = "Minimal"
"""


def _write_toml(content: str) -> Path:
    """Write TOML content to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False)
    tmp.write(content)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


class TestLoadFullConfig(unittest.TestCase):
    """Test loading a complete TOML config with all sections."""

    def setUp(self):
        self.path = _write_toml(FULL_TOML)
        self.config = load_config(self.path)

    def test_agent_name(self):
        self.assertEqual(self.config.name, "TestBot")

    def test_agent_role(self):
        self.assertEqual(self.config.role, "Unit test agent")

    def test_agent_model(self):
        self.assertEqual(self.config.model, "claude-sonnet-4-6")

    def test_personality_trait(self):
        self.assertEqual(self.config.personality.trait, "Curious")

    def test_personality_voice(self):
        self.assertEqual(self.config.personality.voice, "Warm and exploratory")

    def test_personality_focus(self):
        self.assertEqual(self.config.personality.focus, ["physics", "philosophy"])

    def test_personality_emotions(self):
        self.assertEqual(self.config.personality.emotions, {
            "primary": "curiosity", "secondary": "joy"
        })

    def test_memory_chonk_url(self):
        self.assertEqual(self.config.memory.chonk_url, "http://localhost:8080")

    def test_memory_radio_url(self):
        self.assertEqual(self.config.memory.radio_url, "http://localhost:9090")

    def test_memory_clock_tick(self):
        self.assertEqual(self.config.memory.clock_tick_secs, 3600)

    def test_memory_dream_threshold(self):
        self.assertEqual(self.config.memory.dream_threshold_bytes, 32)

    def test_training_patterns(self):
        self.assertEqual(self.config.training.keystone_patterns, ["theorem", "definition", "axiom"])

    def test_training_decay_keystone(self):
        self.assertEqual(self.config.training.decay_alpha_keystone, 0.002)

    def test_training_decay_normal(self):
        self.assertEqual(self.config.training.decay_alpha_normal, 0.015)

    def test_training_dreams_per_chapter(self):
        self.assertEqual(self.config.training.dreams_per_chapter, 5)

    def test_training_chunk_size(self):
        self.assertEqual(self.config.training.chunk_size, 256)

    def test_advocate_review_interval(self):
        self.assertEqual(self.config.advocate.review_interval, "daily")

    def test_advocate_min_fidelity(self):
        self.assertEqual(self.config.advocate.min_keystone_fidelity, 0.90)

    def test_advocate_gap_detection(self):
        self.assertFalse(self.config.advocate.gap_detection)

    def test_advocate_challenge_rate(self):
        self.assertEqual(self.config.advocate.challenge_rate, 0.2)

    def test_advocate_source_verification(self):
        self.assertTrue(self.config.advocate.source_verification)

    def test_graph_auto_connect(self):
        self.assertTrue(self.config.graph.auto_connect)

    def test_graph_causal_labels(self):
        self.assertIn("triggered", self.config.graph.causal_labels)

    def test_tools(self):
        self.assertEqual(self.config.tools, ["remember", "recall", "dream"])


class TestDefaultValues(unittest.TestCase):
    """Test that defaults are applied when sections are missing."""

    def setUp(self):
        self.path = _write_toml(MINIMAL_TOML)
        self.config = load_config(self.path)

    def test_name_from_toml(self):
        self.assertEqual(self.config.name, "Minimal")

    def test_default_role(self):
        self.assertEqual(self.config.role, "General purpose agent")

    def test_default_model(self):
        self.assertEqual(self.config.model, "claude-sonnet-4-6")

    def test_default_personality(self):
        self.assertEqual(self.config.personality.trait, "Neutral")
        self.assertEqual(self.config.personality.voice, "Clear and direct")
        self.assertEqual(self.config.personality.focus, [])

    def test_default_memory(self):
        self.assertEqual(self.config.memory.chonk_url, "http://nemesis:8080")
        self.assertEqual(self.config.memory.clock_tick_secs, 43200)
        self.assertEqual(self.config.memory.dream_threshold_bytes, 16)

    def test_default_training(self):
        self.assertEqual(self.config.training.keystone_patterns, [])
        self.assertEqual(self.config.training.decay_alpha_keystone, 0.003)
        self.assertEqual(self.config.training.decay_alpha_normal, 0.010)

    def test_default_advocate(self):
        self.assertEqual(self.config.advocate.min_keystone_fidelity, 0.95)
        self.assertTrue(self.config.advocate.gap_detection)
        self.assertEqual(self.config.advocate.challenge_rate, 0.1)

    def test_default_graph(self):
        self.assertFalse(self.config.graph.auto_connect)
        self.assertFalse(self.config.graph.edge_discovery)

    def test_default_tools(self):
        self.assertIn("remember", self.config.tools)
        self.assertIn("recall", self.config.tools)
        self.assertIn("status", self.config.tools)

    def test_port_property(self):
        self.assertIsNone(self.config.port)


class TestNameFallback(unittest.TestCase):
    """Test that name falls back to filename stem when not specified."""

    def test_name_from_filename(self):
        toml_content = "[agent]\nrole = \"test\"\n"
        path = _write_toml(toml_content)
        config = load_config(path)
        # Should capitalize the temp filename stem
        self.assertTrue(config.name)
        self.assertIsInstance(config.name, str)


if __name__ == "__main__":
    unittest.main()
