import tempfile
import unittest
from pathlib import Path

from keepsake.patterns import DEFAULT_INCLUDE, discover, display_path, glob_to_regex, matches


class Globs(unittest.TestCase):
    def test_double_star_matches_any_depth(self):
        rx = glob_to_regex("**/CLAUDE.md")
        for p in ["CLAUDE.md", "a/CLAUDE.md", "a/b/CLAUDE.md"]:
            self.assertTrue(rx.match(p), p)
        self.assertFalse(rx.match("a/CLAUDE.md.bak"))

    def test_rule_folders_that_agents_read_are_memory(self):
        root = Path("/p")
        for rel in (".clinerules/01-style.md", ".windsurf/rules/x.md",
                    ".github/instructions/api.instructions.md", ".github/instructions/a/b.instructions.md"):
            self.assertTrue(any(matches(root / rel, p, root) for p in DEFAULT_INCLUDE), rel)
        self.assertFalse(any(matches(root / ".github/workflows/ci.yml", p, root) for p in DEFAULT_INCLUDE))

    def test_single_star_stays_in_one_segment(self):
        rx = glob_to_regex(".claude/*.md")
        self.assertTrue(rx.match(".claude/notes.md"))
        self.assertFalse(rx.match(".claude/deep/notes.md"))

    def test_discover_skips_node_modules_and_git(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "CLAUDE.md").write_text("a")
            (root / "sub").mkdir()
            (root / "sub" / "AGENTS.md").write_text("b")
            (root / "node_modules" / "x").mkdir(parents=True)
            (root / "node_modules" / "x" / "CLAUDE.md").write_text("c")
            (root / ".claude" / "memory").mkdir(parents=True)
            (root / ".claude" / "memory" / "notes.md").write_text("d")
            (root / "README.md").write_text("e")
            found = {display_path(p, root) for p in discover(root, DEFAULT_INCLUDE)}
            self.assertEqual(found, {"CLAUDE.md", "sub/AGENTS.md", ".claude/memory/notes.md"})

    def test_matches_is_relative_to_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertTrue(matches(root / "x" / "CLAUDE.md", "**/CLAUDE.md", root))
            self.assertFalse(matches(root / "x" / "README.md", "**/CLAUDE.md", root))
            self.assertFalse(matches(Path("/elsewhere/CLAUDE.md"), "**/CLAUDE.md", root))

    def test_display_path_outside_root_uses_home(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            shown = display_path(Path.home() / ".claude" / "CLAUDE.md", root)
            self.assertEqual(shown, "~/.claude/CLAUDE.md")


if __name__ == "__main__":
    unittest.main()
