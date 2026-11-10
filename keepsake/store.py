"""Where the approved memory lives, and where held changes wait.

.keepsake/
  config.json      which files count as memory (include patterns)
  index.json       path -> sha256 of the approved content
  approved/<sha>   the approved content itself, one file per distinct content
  pending/<id>.json  a change the agent made that the person has not seen yet
  rejected/<id>.diff a change the person turned down, kept as a record
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .patterns import DEFAULT_INCLUDE, HOME_INCLUDE

STORE_DIR = ".keepsake"
VERSION = 1


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Pending:
    id: str
    path: str
    content: str
    held_at: str
    severity: str
    summary: list[str]


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.dir = self.root / STORE_DIR

    # ---- discovery -------------------------------------------------------

    @classmethod
    def find(cls, start: Path) -> "Store | None":
        """Walk up from `start` to the nearest initialised store."""
        current = start.resolve()
        for candidate in [current, *current.parents]:
            if (candidate / STORE_DIR / "index.json").is_file():
                return cls(candidate)
        return None

    @property
    def initialised(self) -> bool:
        return (self.dir / "index.json").is_file()

    # ---- config ----------------------------------------------------------

    def config(self) -> dict:
        path = self.dir / "config.json"
        if path.is_file():
            return json.loads(path.read_text("utf-8"))
        return {"version": VERSION, "include": list(DEFAULT_INCLUDE)}

    def write_config(self, config: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", "utf-8")

    def include(self) -> list[str]:
        return list(self.config().get("include", DEFAULT_INCLUDE))

    def exclude(self) -> set[str]:
        """Folder names to skip on top of the built-in ones, from config.json."""
        return set(self.config().get("exclude", []))

    def add_home(self) -> None:
        config = self.config()
        for pattern in HOME_INCLUDE:
            if pattern not in config["include"]:
                config["include"].append(pattern)
        self.write_config(config)

    # ---- approved baseline ----------------------------------------------

    def index(self) -> dict[str, str]:
        path = self.dir / "index.json"
        if not path.is_file():
            return {}
        data = json.loads(path.read_text("utf-8"))
        return dict(data.get("files", {}))

    def write_index(self, files: dict[str, str]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "approved").mkdir(exist_ok=True)
        (self.dir / ".gitignore").write_text("pending/\n", "utf-8")
        payload = {
            "version": VERSION,
            "approved_at": _now(),
            "files": dict(sorted(files.items())),
        }
        (self.dir / "index.json").write_text(json.dumps(payload, indent=2) + "\n", "utf-8")

    def approved_content(self, sha: str) -> str | None:
        blob = self.dir / "approved" / sha
        if blob.is_file():
            return blob.read_text("utf-8")
        return None

    def approve(self, key: str, content: str) -> str:
        """Record `content` as the approved version of the memory file `key`."""
        sha = sha256(content)
        (self.dir / "approved").mkdir(parents=True, exist_ok=True)
        blob = self.dir / "approved" / sha
        if not blob.is_file():
            blob.write_text(content, "utf-8")
        files = self.index()
        files[key] = sha
        self.write_index(files)
        return sha

    def forget(self, key: str) -> None:
        files = self.index()
        files.pop(key, None)
        self.write_index(files)

    # ---- pending ---------------------------------------------------------

    def hold(self, key: str, content: str, severity: str, summary: list[str]) -> Pending:
        pending_dir = self.dir / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        pid = time.strftime("%Y%m%dT%H%M%S") + "-" + sha256(content)[:8]
        item = Pending(pid, key, content, _now(), severity, summary)
        (pending_dir / f"{pid}.json").write_text(json.dumps(item.__dict__, indent=2) + "\n", "utf-8")
        return item

    def pending(self) -> list[Pending]:
        pending_dir = self.dir / "pending"
        if not pending_dir.is_dir():
            return []
        items = []
        for path in sorted(pending_dir.glob("*.json")):
            data = json.loads(path.read_text("utf-8"))
            items.append(Pending(**data))
        return items

    def drop_pending(self, pid: str) -> None:
        path = self.dir / "pending" / f"{pid}.json"
        if path.is_file():
            path.unlink()

    # ---- approvals log ---------------------------------------------------

    def log_approval(self, key: str, severity: str, note: str = "", source: str = "live") -> None:
        """One line per decision, so the history of yes and no can be read back."""
        line = f"{_now()}\tapproved\t{key}\t{severity}\t{source}\t{note}\n"
        with (self.dir / "decisions.log").open("a", encoding="utf-8") as fh:
            fh.write(line)

    def log_rejection(self, key: str, severity: str, note: str = "", source: str = "live") -> None:
        line = f"{_now()}\trejected\t{key}\t{severity}\t{source}\t{note}\n"
        with (self.dir / "decisions.log").open("a", encoding="utf-8") as fh:
            fh.write(line)

    # ---- rejected --------------------------------------------------------

    def record_rejection(self, key: str, diff_text: str) -> Path:
        rejected = self.dir / "rejected"
        rejected.mkdir(parents=True, exist_ok=True)
        name = time.strftime("%Y%m%dT%H%M%S") + "-" + key.replace("/", "__").replace("~", "home") + ".diff"
        path = rejected / name
        path.write_text(diff_text, "utf-8")
        return path


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
