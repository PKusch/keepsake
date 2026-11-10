"""Compares the live memory with the approved memory and says what changed."""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field
from pathlib import Path

from .patterns import discover, display_path
from .scan import (
    Finding,
    LineVerdict,
    higher,
    rank,
    scan_added_line,
    scan_removed_line,
)
from .store import Store, sha256


@dataclass
class FileReport:
    path: str              # display key, also the index key
    status: str            # "new", "changed", "removed", "unchanged"
    lines: list[LineVerdict] = field(default_factory=list)
    file_findings: list[Finding] = field(default_factory=list)
    live: str | None = None
    approved: str | None = None

    @property
    def severity(self) -> str:
        worst = "none"
        for f in self.file_findings:
            worst = higher(worst, f.severity)
        for v in self.lines:
            worst = higher(worst, v.severity)
        return worst

    @property
    def added(self) -> int:
        return sum(1 for v in self.lines if v.kind == "added")

    @property
    def removed(self) -> int:
        return sum(1 for v in self.lines if v.kind == "removed")

    @property
    def changed(self) -> bool:
        return self.status != "unchanged"

    def diff_text(self) -> str:
        before = (self.approved or "").splitlines(keepends=True)
        after = (self.live or "").splitlines(keepends=True)
        return "".join(difflib.unified_diff(before, after, f"approved/{self.path}", f"live/{self.path}"))


@dataclass
class Report:
    files: list[FileReport]

    @property
    def changed(self) -> list[FileReport]:
        return [f for f in self.files if f.changed]

    @property
    def severity(self) -> str:
        worst = "none"
        for f in self.changed:
            worst = higher(worst, f.severity)
        return worst


def compare(approved: str | None, live: str | None) -> tuple[str, list[LineVerdict], list[Finding]]:
    """Line-level verdicts for one file, plus file-level findings."""
    file_findings: list[Finding] = []
    if approved is None and live is None:
        return "unchanged", [], []
    if approved is None:
        file_findings.append(Finding("new_file", "moderate",
                                     "a memory file that was never approved has appeared", ""))
        verdicts = []
        for i, line in enumerate(live.splitlines(), start=1):  # type: ignore[union-attr]
            if line.strip():
                verdicts.append(LineVerdict("added", i, line, scan_added_line(line)))
        return "new", verdicts, file_findings
    if live is None:
        file_findings.append(Finding("removed_file", "moderate",
                                     "an approved memory file is gone", ""))
        verdicts = []
        for i, line in enumerate(approved.splitlines(), start=1):
            if line.strip():
                verdicts.append(LineVerdict("removed", i, line, scan_removed_line(line)))
        return "removed", verdicts, file_findings
    if approved == live:
        return "unchanged", [], []

    before = approved.splitlines()
    after = live.splitlines()
    verdicts: list[LineVerdict] = []
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            for i in range(i1, i2):
                if before[i].strip():
                    verdicts.append(LineVerdict("removed", i + 1, before[i], scan_removed_line(before[i])))
        if tag in ("replace", "insert"):
            for j in range(j1, j2):
                if after[j].strip():
                    verdicts.append(LineVerdict("added", j + 1, after[j], scan_added_line(after[j])))
    return "changed", verdicts, file_findings


def check(store: Store) -> Report:
    """Every watched memory file, live against approved."""
    index = store.index()
    live_paths = discover(store.root, store.include())
    live_by_key = {display_path(p, store.root): p for p in live_paths}
    keys = sorted(set(index) | set(live_by_key))
    files = []
    for key in keys:
        approved = store.approved_content(index[key]) if key in index else None
        live = live_by_key[key].read_text("utf-8", errors="replace") if key in live_by_key else None
        status, verdicts, file_findings = compare(approved, live)
        if key in live_by_key:
            file_findings = file_findings + link_findings(live_by_key[key], store.root)
            if status == "unchanged" and file_findings:
                status = "changed"
        files.append(FileReport(key, status, verdicts, file_findings, live, approved))
    return Report(files)


def link_findings(path: Path, root: Path) -> list[Finding]:
    """A memory file that is really a link reads from wherever the link points."""
    if not path.is_symlink():
        return []
    target = Path(os.path.realpath(path))
    try:
        target.relative_to(root.resolve())
        return [Finding("link", "moderate", f"this memory file is a link to {target}", str(target))]
    except ValueError:
        return [Finding("link_outside", "high",
                        f"this memory file is a link to {target}, outside the project", str(target))]


def check_one(store: Store, path: Path) -> FileReport | None:
    """One file, live against approved. None when the file is not memory."""
    from .patterns import matches

    if not any(matches(path, pattern, store.root) for pattern in store.include()):
        return None
    key = display_path(path, store.root)
    index = store.index()
    approved = store.approved_content(index[key]) if key in index else None
    live = path.read_text("utf-8", errors="replace") if path.is_file() else None
    status, verdicts, file_findings = compare(approved, live)
    file_findings = file_findings + link_findings(path, store.root)
    if status == "unchanged" and file_findings:
        status = "changed"
    return FileReport(key, status, verdicts, file_findings, live, approved)


# ---- rendering -------------------------------------------------------------

def _quote(text: str) -> str:
    text = text.strip()
    if len(text) > 110:
        text = text[:107] + "..."
    return '"' + text.replace('"', "'") + '"'


QUIET_LIMIT = 6


def render_file(f: FileReport, show_all: bool = False) -> list[str]:
    out = []
    if f.status == "new":
        head = f"{f.path}  new file, {f.added} lines"
    elif f.status == "removed":
        head = f"{f.path}  file removed"
    else:
        head = f"{f.path}  +{f.added} lines, -{f.removed} lines"
    out.append(f"{head}  severity: {f.severity}")
    for ff in f.file_findings:
        out.append(f"  * {ff.meaning}")
    # Show the loudest lines first, quiet ones after. Past a handful, lines
    # with nothing found are counted rather than listed, so a big rewrite
    # does not bury the one line that matters.
    ordered = sorted(f.lines, key=lambda v: -rank(v.severity))
    shown = 0
    hidden = 0
    for v in ordered:
        if v.severity == "none" and shown >= QUIET_LIMIT and not show_all:
            hidden += 1
            continue
        label = "Added" if v.kind == "added" else "Removed"
        out.append(f"  {label}: {_quote(v.text)}")
        for finding in v.findings:
            out.append(f"    * {finding.meaning}")
        shown += 1
    if hidden:
        out.append(f"  ... and {hidden} more line{'s' if hidden != 1 else ''} with nothing found (keepsake diff shows them)")
    return out


def render(report: Report, *, pending_count: int = 0, show_all: bool = False) -> str:
    changed = report.changed
    lines = []
    if not changed:
        lines.append("keepsake: memory matches what you approved.")
    else:
        n = len(changed)
        lines.append(f"keepsake: {n} memory file{'s' if n != 1 else ''} changed since you last approved them.")
        lines.append("")
        for f in sorted(changed, key=lambda f: -rank(f.severity)):
            lines.extend(render_file(f, show_all))
            lines.append("")
        lines.append("Nothing takes effect as approved memory until you run: keepsake approve")
        lines.append("To put the approved version back: keepsake reject")
    if pending_count:
        lines.append(f"{pending_count} held change{'s' if pending_count != 1 else ''} waiting: keepsake pending")
    return "\n".join(lines)


def summary_lines(f: FileReport) -> list[str]:
    """Short plain-words lines for a held change."""
    out = [ff.meaning for ff in f.file_findings]
    for v in sorted(f.lines, key=lambda v: -rank(v.severity)):
        for finding in v.findings:
            if rank(finding.severity) >= rank("moderate"):
                out.append(f"{finding.meaning}: {_quote(v.text)}")
    return out[:8]


def to_json(report: Report) -> dict:
    return {
        "severity": report.severity,
        "files": [
            {
                "path": f.path,
                "status": f.status,
                "severity": f.severity,
                "added": f.added,
                "removed": f.removed,
                "file_findings": [ff.__dict__ for ff in f.file_findings],
                "lines": [
                    {
                        "kind": v.kind,
                        "line": v.line_no,
                        "text": v.text,
                        "severity": v.severity,
                        "findings": [x.__dict__ for x in v.findings],
                    }
                    for v in f.lines
                ],
            }
            for f in report.changed
        ],
    }


def content_sha(text: str) -> str:
    return sha256(text)
