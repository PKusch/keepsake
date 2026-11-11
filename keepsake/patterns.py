"""Which files count as an agent's memory, and how to match them."""

from __future__ import annotations

import os
import re
from pathlib import Path

# Files that coding agents read at the start of every session and write to
# between sessions. Anything here steers future behaviour, so a change to it
# is treated like a tool call that needs the person's say-so.
DEFAULT_INCLUDE = [
    "**/CLAUDE.md",
    "**/CLAUDE.local.md",
    "**/AGENTS.md",
    "**/GEMINI.md",
    "**/MEMORY.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    ".clinerules/**",  # Cline also reads a folder of rule files
    ".windsurf/rules/**",
    ".github/copilot-instructions.md",
    ".github/instructions/**/*.instructions.md",  # Copilot's per-path instructions
    ".claude/**/*.md",
    ".cursor/rules/**",
    "memory/**/*.md",
]

# Memory that lives outside any one project and so reaches every project.
HOME_INCLUDE = [
    "~/.claude/CLAUDE.md",
    "~/.claude/projects/*/memory/**/*.md",
]

EXCLUDE_DIRS = {
    ".git",
    ".keepsake",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".npm-cache",
}

_GLOB_CHARS = re.compile(r"[*?\[]")


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob with ** into a regex over a posix path."""
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    # Ignore case: on a file system that ignores it (the macOS default) an agent
    # writing claude.md changes the CLAUDE.md the next session reads, and that
    # write slipped past the guard. Holding a claude.md on Linux too is harmless.
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def expand(pattern: str) -> str:
    return os.path.expanduser(pattern)


def is_absolute_pattern(pattern: str) -> bool:
    return pattern.startswith("~") or os.path.isabs(pattern)


def pattern_base(pattern: str) -> Path:
    """The deepest directory in a pattern that has no glob characters."""
    parts = Path(expand(pattern)).parts
    base: list[str] = []
    for part in parts:
        if _GLOB_CHARS.search(part):
            break
        base.append(part)
    return Path(*base) if base else Path(".")


def _on_disk_name(parent: Path, name: str) -> str:
    """The file name as the folder spells it. Where the file system ignores
    case, claude.md opens CLAUDE.md, and the approved copy is filed under the
    folder's spelling, so the guard must find it by that name."""
    try:
        entries = os.listdir(parent)
    except OSError:
        return name
    if name in entries:
        return name
    folded = [e for e in entries if e.casefold() == name.casefold()]
    return folded[0] if len(folded) == 1 and (parent / name).exists() else name


def canonical(path: Path) -> Path:
    """Resolve the folder, keep the file name: links in the file are kept visible."""
    path = Path(os.path.abspath(path))
    parent = Path(os.path.realpath(path.parent))
    return parent / _on_disk_name(parent, path.name)


def matches(path: Path, pattern: str, root: Path) -> bool:
    """True when `path` is named by `pattern` (relative to `root` unless absolute)."""
    regex = glob_to_regex(expand(pattern))
    if is_absolute_pattern(pattern):
        return bool(regex.match(path.as_posix()))
    # The file itself is not resolved: a memory file that is a link must
    # still be found under its own name, and then reported as a link.
    try:
        rel = canonical(path).relative_to(root.resolve())
    except ValueError:
        return False
    return bool(regex.match(rel.as_posix()))


def discover(root: Path, include: list[str], exclude: set[str] | None = None) -> list[Path]:
    """Every existing file named by the include patterns, as absolute paths."""
    skip = EXCLUDE_DIRS | (exclude or set())
    found: set[Path] = set()
    for pattern in include:
        base = pattern_base(pattern) if is_absolute_pattern(pattern) else root / pattern_base(pattern)
        if base.is_file():
            if matches(base, pattern, root):
                found.add(canonical(base))
            continue
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                candidate = Path(dirpath) / name
                if matches(candidate, pattern, root):
                    found.add(canonical(candidate))
    return sorted(found)


def display_path(path: Path, root: Path) -> str:
    """Relative inside the project, `~`-shortened outside it."""
    absolute = canonical(path)
    try:
        return absolute.relative_to(root.resolve()).as_posix()
    except ValueError:
        home = Path.home().resolve()
        try:
            return "~/" + absolute.relative_to(home).as_posix()
        except ValueError:
            return path.as_posix()
