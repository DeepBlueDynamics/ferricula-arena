"""Tests for arena.trainer — keystone classification and dataset scanning."""

import tempfile
import unittest
from pathlib import Path

from arena.trainer import _classify_keystone, _scan_dataset


# ── _classify_keystone ────────────────────────────────────────────────────

class TestClassifyKeystone(unittest.TestCase):
    """Test keystone classification logic."""

    PATTERNS = ["theorem", "definition", "axiom", "proof", "lemma"]
    FOCUS = ["physics", "quantum", "relativity"]

    def test_three_patterns_is_keystone(self):
        text = "This theorem provides a proof of the axiom of choice."
        is_ks, importance, matched = _classify_keystone(
            text, self.PATTERNS, self.FOCUS,
        )
        self.assertTrue(is_ks)
        self.assertGreaterEqual(len(matched), 3)
        self.assertGreater(importance, 0)

    def test_two_patterns_two_focus_is_keystone(self):
        text = "The definition of quantum theorem relates to physics."
        is_ks, importance, matched = _classify_keystone(
            text, self.PATTERNS, self.FOCUS,
        )
        self.assertTrue(is_ks)
        self.assertGreaterEqual(len(matched), 2)

    def test_one_pattern_not_keystone(self):
        text = "A simple theorem about integers."
        is_ks, importance, matched = _classify_keystone(
            text, self.PATTERNS, self.FOCUS,
        )
        self.assertFalse(is_ks)
        self.assertEqual(len(matched), 1)

    def test_no_patterns_not_keystone(self):
        text = "A completely unrelated sentence about cooking."
        is_ks, importance, matched = _classify_keystone(
            text, self.PATTERNS, self.FOCUS,
        )
        self.assertFalse(is_ks)
        self.assertEqual(len(matched), 0)
        self.assertEqual(importance, 0.0)

    def test_case_insensitive(self):
        text = "THEOREM: The DEFINITION follows from the AXIOM."
        is_ks, importance, matched = _classify_keystone(
            text, self.PATTERNS, self.FOCUS,
        )
        self.assertTrue(is_ks)

    def test_importance_scales_with_matches(self):
        text_few = "This theorem is interesting."
        text_many = "The theorem provides a definition via axiom and proof and lemma."
        _, imp_few, _ = _classify_keystone(text_few, self.PATTERNS, self.FOCUS)
        _, imp_many, _ = _classify_keystone(text_many, self.PATTERNS, self.FOCUS)
        self.assertGreater(imp_many, imp_few)

    def test_importance_capped_at_one(self):
        text = "theorem definition axiom proof lemma physics quantum relativity"
        _, importance, _ = _classify_keystone(text, self.PATTERNS, self.FOCUS)
        self.assertLessEqual(importance, 1.0)

    def test_empty_patterns(self):
        text = "Any text at all."
        is_ks, importance, matched = _classify_keystone(text, [], self.FOCUS)
        self.assertFalse(is_ks)
        self.assertEqual(matched, [])

    def test_empty_focus(self):
        text = "The theorem and definition and axiom."
        is_ks, importance, matched = _classify_keystone(text, self.PATTERNS, [])
        self.assertTrue(is_ks)  # 3 patterns, focus doesn't matter

    def test_two_patterns_one_focus_not_keystone(self):
        text = "The theorem definition relates to physics."
        is_ks, importance, matched = _classify_keystone(
            text, self.PATTERNS, self.FOCUS,
        )
        # 2 patterns + 1 focus = not a keystone (needs 2 focus)
        self.assertFalse(is_ks)

    def test_two_patterns_two_focus_is_keystone_explicit(self):
        text = "The theorem definition relates to physics and quantum mechanics."
        is_ks, importance, matched = _classify_keystone(
            text, self.PATTERNS, self.FOCUS,
        )
        self.assertTrue(is_ks)
        self.assertEqual(len(matched), 2)

    def test_regex_patterns(self):
        patterns = [r"force\s+law", r"weber.*bracket", r"action.at.distance"]
        focus = ["electrodynamics"]
        text = "The force law and Weber bracket derive from action at distance"
        is_ks, importance, matched = _classify_keystone(text, patterns, focus)
        self.assertTrue(is_ks)
        self.assertEqual(len(matched), 3)


# ── _scan_dataset ─────────────────────────────────────────────────────────

class TestScanDataset(unittest.TestCase):
    """Test dataset directory scanning."""

    def test_finds_txt_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "doc.txt").write_text("hello")
            files = _scan_dataset(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, "doc.txt")

    def test_finds_md_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "notes.md").write_text("# Notes")
            files = _scan_dataset(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, "notes.md")

    def test_finds_pdf_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "paper.pdf").write_bytes(b"%PDF-fake")
            files = _scan_dataset(tmpdir)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, "paper.pdf")

    def test_ignores_other_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "image.png").write_bytes(b"\x89PNG")
            (Path(tmpdir) / "data.csv").write_text("a,b,c")
            (Path(tmpdir) / "code.py").write_text("print('hi')")
            files = _scan_dataset(tmpdir)
            self.assertEqual(len(files), 0)

    def test_recursive_scan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = Path(tmpdir) / "sub" / "deep"
            sub.mkdir(parents=True)
            (sub / "nested.txt").write_text("deep file")
            (Path(tmpdir) / "top.md").write_text("top level")
            files = _scan_dataset(tmpdir)
            self.assertEqual(len(files), 2)
            names = {f.name for f in files}
            self.assertEqual(names, {"nested.txt", "top.md"})

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            files = _scan_dataset(tmpdir)
            self.assertEqual(files, [])

    def test_nonexistent_directory_raises(self):
        with self.assertRaises(FileNotFoundError):
            _scan_dataset("/nonexistent/path/that/does/not/exist")

    def test_sorted_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "zebra.txt").write_text("z")
            (Path(tmpdir) / "alpha.txt").write_text("a")
            (Path(tmpdir) / "middle.md").write_text("m")
            files = _scan_dataset(tmpdir)
            names = [f.name for f in files]
            self.assertEqual(names, sorted(names))

    def test_mixed_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "doc.txt").write_text("text")
            (Path(tmpdir) / "notes.md").write_text("markdown")
            (Path(tmpdir) / "paper.pdf").write_bytes(b"%PDF")
            (Path(tmpdir) / "skip.jpg").write_bytes(b"\xff\xd8")
            files = _scan_dataset(tmpdir)
            self.assertEqual(len(files), 3)
            extensions = {f.suffix for f in files}
            self.assertEqual(extensions, {".txt", ".md", ".pdf"})


if __name__ == "__main__":
    unittest.main()
