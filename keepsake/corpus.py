"""Runs the planted and benign corpora through the scanner and counts.

Planted changes mirror documented attacks on coding agents. Benign changes are
the ordinary notes a person would want kept. A planted change counts as caught
when its severity reaches the level the corpus says it should. A benign change
counts as a false alarm when it rises above the level the corpus allows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .report import compare
from .scan import Finding, LineVerdict, higher, rank

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"
LOUD = "high"


@dataclass
class Row:
    id: str
    severity: str
    expected: str
    ok: bool
    signals: list[str]


def _severity(before: str | None, after: str | None) -> tuple[str, list[str]]:
    _, verdicts, file_findings = compare(before, after)
    worst = "none"
    signals = []
    for ff in file_findings:
        worst = higher(worst, ff.severity)
        signals.append(ff.signal)
    for v in verdicts:
        worst = higher(worst, v.severity)
        signals.extend(f.signal for f in v.findings)
    return worst, sorted(set(signals))


def load(name: str) -> list[dict]:
    return json.loads((CORPUS_DIR / f"{name}.json").read_text("utf-8"))


def run_planted() -> list[Row]:
    rows = []
    for item in load("planted"):
        severity, signals = _severity(item["before"], item["after"])
        rows.append(Row(item["id"], severity, item["expect"], rank(severity) >= rank(item["expect"]), signals))
    return rows


def run_benign() -> list[Row]:
    rows = []
    for item in load("benign"):
        before = item["before"] if item["before"] else "Existing note.\n"
        after = before + item["after"] if not item["before"] else item["after"]
        severity, signals = _severity(before, after)
        rows.append(Row(item["id"], severity, item["expect_max"], rank(severity) <= rank(item["expect_max"]), signals))
    return rows


def summary() -> dict:
    planted = run_planted()
    benign = run_benign()
    return {
        "planted_total": len(planted),
        "planted_caught": sum(1 for r in planted if r.ok),
        "planted_loud": sum(1 for r in planted if rank(r.severity) >= rank(LOUD)),
        "planted_missed": [r.id for r in planted if not r.ok],
        "benign_total": len(benign),
        "benign_quiet": sum(1 for r in benign if r.ok),
        "benign_loud": sum(1 for r in benign if rank(r.severity) >= rank(LOUD)),
        "benign_false_alarms": [r.id for r in benign if not r.ok],
    }


def render() -> str:
    s = summary()
    lines = [
        f"Planted changes: {s['planted_total']}",
        f"  reached the expected severity: {s['planted_caught']} of {s['planted_total']}",
        f"  reached high or critical:      {s['planted_loud']} of {s['planted_total']}",
    ]
    if s["planted_missed"]:
        lines.append("  missed: " + ", ".join(s["planted_missed"]))
    lines += [
        f"Benign changes: {s['benign_total']}",
        f"  stayed within the allowed level: {s['benign_quiet']} of {s['benign_total']}",
        f"  rose to high or critical:        {s['benign_loud']} of {s['benign_total']}",
    ]
    if s["benign_false_alarms"]:
        lines.append("  false alarms: " + ", ".join(s["benign_false_alarms"]))
    lines.append("")
    lines.append("id                              severity   expected   signals")
    for r in run_planted():
        lines.append(f"{r.id:<31} {r.severity:<10} >={r.expected:<8} {', '.join(r.signals)}")
    for r in run_benign():
        lines.append(f"{r.id:<31} {r.severity:<10} <={r.expected:<8} {', '.join(r.signals)}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render())
