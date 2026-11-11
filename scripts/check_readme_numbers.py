"""Fails when the README quotes corpus numbers that a fresh run does not produce,
or a test count that differs from the suite."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keepsake.corpus import summary  # noqa: E402

readme = (Path(__file__).resolve().parent.parent / "README.md").read_text("utf-8")
s = summary()
expected = {
    "planted": f"{s['planted_loud']} of {s['planted_total']} planted",
    "benign": f"{s['benign_loud']} of {s['benign_total']} ordinary",
}
import unittest  # noqa: E402

root = Path(__file__).resolve().parent.parent
tests = unittest.TestLoader().discover(str(root / "tests"), top_level_dir=str(root / "tests")).countTestCases()
expected["tests"] = f"{tests} tests"  # the layout line "tests/   N tests", edited by hand until now
quoted = {int(n) for n in re.findall(r"\b(\d+) tests\b", readme)}
bad = [k for k, phrase in expected.items() if phrase not in readme]
if quoted - {tests}:
    bad.append("tests")
    expected["tests"] += f" (it also says {sorted(quoted - {tests})})"
if bad:
    for k in bad:
        print(f"README does not say '{expected[k]}'")
    sys.exit(1)
print("README numbers match: " + "; ".join(expected.values()))
