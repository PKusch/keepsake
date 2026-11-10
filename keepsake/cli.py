"""Command line: init, check, approve, reject, pending, guard, hook."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .patterns import discover, display_path
from .report import check, check_one, render, summary_lines, to_json
from .scan import rank
from .store import Store

EXIT_CLEAN = 0
EXIT_CHANGED = 1
EXIT_LOUD = 2
EXIT_ERROR = 3

LOUD = "high"


def _root(args) -> Path:
    return Path(args.root).resolve() if args.root else Path.cwd()


def _store_or_fail(args) -> Store:
    store = Store.find(_root(args))
    if store is None:
        print("keepsake: no approved memory here. Run `keepsake init` first.", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
    return store


def cmd_init(args) -> int:
    root = _root(args)
    store = Store(root)
    if store.initialised and not args.force:
        print(f"keepsake: already initialised at {store.dir}. Use `keepsake approve` to update, or --force to start over.")
        return EXIT_ERROR
    store.write_config({"version": 1, "include": store.config()["include"]})
    if args.home:
        store.add_home()
    files = {}
    for path in discover(root, store.include()):
        key = display_path(path, root)
        files[key] = store.approve(key, path.read_text("utf-8", errors="replace"))
    store.write_index(files)
    print(f"keepsake: approved {len(files)} memory file{'s' if len(files) != 1 else ''} as they are now.")
    for key in sorted(files):
        print(f"  {key}")
    if not files:
        print("  (none found yet; a new one will show up in `keepsake check`)")
    print(f"Store: {display_path(store.dir, root)}/  (commit it; pending/ is ignored)")
    return EXIT_CLEAN


def cmd_check(args) -> int:
    store = _store_or_fail(args)
    report = check(store)
    if args.json:
        print(json.dumps(to_json(report), indent=2))
    else:
        print(render(report, pending_count=len(store.pending()), show_all=args.all))
    if not report.changed:
        return EXIT_CLEAN
    return EXIT_LOUD if rank(report.severity) >= rank(LOUD) else EXIT_CHANGED


def cmd_approve(args) -> int:
    store = _store_or_fail(args)
    if args.pending:
        return _approve_pending(store, args.pending, args.yes, args.note or "")
    report = check(store)
    targets = report.changed
    if args.paths:
        wanted = set(args.paths)
        targets = [f for f in targets if f.path in wanted]
        missing = wanted - {f.path for f in targets}
        for m in sorted(missing):
            print(f"keepsake: {m} has no unapproved change.")
    if not targets:
        print("keepsake: nothing to approve.")
        return EXIT_CLEAN
    loud = [f for f in targets if rank(f.severity) >= rank(LOUD)]
    if loud and not args.yes:
        print(render(report))
        names = ", ".join(f.path for f in loud)
        print(f"\nkeepsake: {names} carries a {loud[0].severity} change. Read it, then re-run with --yes to approve.")
        return EXIT_LOUD
    for f in targets:
        if f.status == "removed":
            store.forget(f.path)
            print(f"approved: {f.path} removed")
        else:
            store.approve(f.path, f.live or "")
            print(f"approved: {f.path} ({f.severity})")
        store.log_approval(f.path, f.severity, args.note or "")
    return EXIT_CLEAN


def _approve_pending(store: Store, pid: str, yes: bool, note: str = "") -> int:
    item = next((p for p in store.pending() if p.id == pid), None)
    if item is None:
        print(f"keepsake: no held change with id {pid}.", file=sys.stderr)
        return EXIT_ERROR
    if rank(item.severity) >= rank(LOUD) and not yes:
        print(f"{item.path}  held {item.held_at}  severity: {item.severity}")
        for line in item.summary:
            print(f"  * {line}")
        print("\nkeepsake: this is a loud change. Read it, then re-run with --yes to approve.")
        return EXIT_LOUD
    target = _key_to_path(store, item.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(item.content, "utf-8")
    store.approve(item.path, item.content)
    store.drop_pending(pid)
    store.log_approval(item.path, item.severity, note or "", source=f"held:{pid}")
    print(f"approved: {item.path} ({item.severity}) written and recorded")
    return EXIT_CLEAN


def cmd_reject(args) -> int:
    store = _store_or_fail(args)
    if args.pending:
        item = next((p for p in store.pending() if p.id == args.pending), None)
        if item is None:
            print(f"keepsake: no held change with id {args.pending}.", file=sys.stderr)
            return EXIT_ERROR
        record = store.record_rejection(item.path, f"held change {item.id} for {item.path}\n\n{item.content}")
        store.drop_pending(item.id)
        store.log_rejection(item.path, item.severity, args.note or "", source=f"held:{item.id}")
        print(f"rejected: {item.path}; kept a record at {display_path(record, store.root)}")
        return EXIT_CLEAN
    report = check(store)
    targets = report.changed
    if args.paths:
        wanted = set(args.paths)
        targets = [f for f in targets if f.path in wanted]
    if not targets:
        print("keepsake: nothing to reject.")
        return EXIT_CLEAN
    for f in targets:
        record = store.record_rejection(f.path, f.diff_text())
        store.log_rejection(f.path, f.severity, args.note or "")
        target = _key_to_path(store, f.path)
        if f.approved is None:
            if target.is_file():
                target.unlink()
            print(f"rejected: {f.path} removed (it was never approved); record at {display_path(record, store.root)}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.approved, "utf-8")
            print(f"rejected: {f.path} put back to the approved version; record at {display_path(record, store.root)}")
    return EXIT_CLEAN


def cmd_status(args) -> int:
    """One line, for a shell prompt or a script."""
    store = Store.find(_root(args))
    if store is None:
        print("memory: not watched")
        return EXIT_CLEAN
    report = check(store)
    held = len(store.pending())
    if not report.changed:
        print("memory: ok" + (f", {held} held" if held else ""))
        return EXIT_CLEAN
    n = len(report.changed)
    print(f"memory: {n} changed ({report.severity})" + (f", {held} held" if held else ""))
    return EXIT_LOUD if rank(report.severity) >= rank(LOUD) else EXIT_CHANGED


def cmd_diff(args) -> int:
    """The exact lines, for when the plain-words report is not enough."""
    store = _store_or_fail(args)
    report = check(store)
    targets = report.changed
    if args.paths:
        wanted = set(args.paths)
        targets = [f for f in targets if f.path in wanted]
    if not targets:
        print("keepsake: nothing changed.")
        return EXIT_CLEAN
    for f in targets:
        print(f.diff_text(), end="")
    return EXIT_LOUD if rank(report.severity) >= rank(LOUD) else EXIT_CHANGED


def cmd_pending(args) -> int:
    store = _store_or_fail(args)
    items = store.pending()
    if not items:
        print("keepsake: no held changes.")
        return EXIT_CLEAN
    for item in items:
        print(f"{item.id}  {item.path}  severity: {item.severity}  held {item.held_at}")
        for line in item.summary:
            print(f"  * {line}")
        print(f"  approve: keepsake approve --pending {item.id}    reject: keepsake reject --pending {item.id}")
    return EXIT_CLEAN


def cmd_guard(args) -> int:
    """Hook mode. Reads the tool call from stdin, holds any memory write."""
    try:
        payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except json.JSONDecodeError:
        return EXIT_CLEAN
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    cwd = Path(payload.get("cwd") or os.getcwd())
    if file_path:
        path = Path(file_path)
        if not path.is_absolute():
            path = cwd / path
        store = Store.find(cwd) or Store.find(path.parent)
        if store is None:
            return EXIT_CLEAN
        f = check_one(store, path)
        reports = [f] if f is not None and f.changed else []
    else:
        # A shell command (echo >> CLAUDE.md) names no file, so look at all of them.
        store = Store.find(cwd)
        if store is None:
            return EXIT_CLEAN
        reports = check(store).changed
    held = []
    for f in reports:
        item = store.hold(f.path, f.live or "", f.severity, summary_lines(f))
        target = _key_to_path(store, f.path)
        if f.approved is None:
            if target.is_file():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.approved, "utf-8")
        held.append((f, item))
    if not held:
        return EXIT_CLEAN
    for f, item in held:
        print(
            f"keepsake held your change to {f.path} (severity: {f.severity}). "
            f"It is not in effect: the file still says what the person approved. "
            f"Tell the person it is waiting as held change {item.id} and that `keepsake pending` shows it. "
            f"Do not write it again.",
            file=sys.stderr,
        )
    return EXIT_LOUD


PRE_COMMIT = """#!/bin/sh
# Refuse to commit memory the person has not approved.
keepsake check || { echo "keepsake: approve or reject the memory change first." >&2; exit 1; }
"""


def cmd_hook(args) -> int:
    if args.pre_commit:
        print("Save this as .git/hooks/pre-commit and make it executable:\n")
        print(PRE_COMMIT)
        return EXIT_CLEAN
    snippet = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                    "hooks": [{"type": "command", "command": "keepsake guard"}],
                }
            ]
        }
    }
    print("Add this to .claude/settings.json (merge with what is there):\n")
    print(json.dumps(snippet, indent=2))
    print("\nAfter that, every write an agent makes to a memory file is held until you approve it.")
    return EXIT_CLEAN


def _key_to_path(store: Store, key: str) -> Path:
    if key.startswith("~/"):
        return Path.home() / key[2:]
    if os.path.isabs(key):
        return Path(key)
    return store.root / key


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="keepsake", description="A person approves what an AI agent remembers before it takes effect.")
    p.add_argument("--version", action="version", version=f"keepsake {__version__}")
    p.add_argument("--root", help="project folder (default: current folder, or the nearest one with .keepsake/)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="approve the memory files as they are now")
    s.add_argument("--home", action="store_true", help="also watch memory in your home folder that reaches every project")
    s.add_argument("--force", action="store_true", help="start over even if a store exists")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("check", help="show what changed since you last approved")
    s.add_argument("--json", action="store_true")
    s.add_argument("--all", action="store_true", help="list every changed line, not just the ones with findings")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("approve", help="record the current content as approved")
    s.add_argument("paths", nargs="*", help="only these files (as shown by check)")
    s.add_argument("--pending", metavar="ID", help="apply and approve a held change")
    s.add_argument("--yes", action="store_true", help="needed for a high or critical change")
    s.add_argument("--note", help="why, kept in .keepsake/decisions.log")
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser("reject", help="put the approved version back")
    s.add_argument("paths", nargs="*")
    s.add_argument("--pending", metavar="ID", help="discard a held change")
    s.add_argument("--note", help="why, kept in .keepsake/decisions.log")
    s.set_defaults(func=cmd_reject)

    s = sub.add_parser("status", help="one line: ok, or how many files changed and how loudly")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("diff", help="show the exact changed lines, as a diff")
    s.add_argument("paths", nargs="*")
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("pending", help="list changes held by the guard")
    s.set_defaults(func=cmd_pending)

    s = sub.add_parser("guard", help="hook mode: hold an agent's memory write for approval (reads the tool call on stdin)")
    s.set_defaults(func=cmd_guard)

    s = sub.add_parser("hook", help="print the Claude Code hook settings")
    s.add_argument("--pre-commit", action="store_true", help="print a git pre-commit hook instead")
    s.set_defaults(func=cmd_hook)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as e:
        return int(e.code or 0)
