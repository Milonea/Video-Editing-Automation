from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHECKPOINT_VERSION = 1
STAGE_STATUSES = {"pending", "running", "completed", "failed", "needs_review", "skipped"}


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_fingerprint(path: str | Path, full_hash: bool = False) -> dict[str, Any]:
    file = Path(path).expanduser().resolve()
    stat = file.stat()
    result: dict[str, Any] = {
        "path": str(file),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "hash_mode": "sha256" if full_hash else "stat",
    }
    if full_hash:
        digest = hashlib.sha256()
        with file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        result["sha256"] = digest.hexdigest()
    return result


def atomic_write_bytes(path: str | Path, payload: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def atomic_write_text(path: str | Path, value: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, value.encode(encoding))


def atomic_write_json(path: str | Path, value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    atomic_write_bytes(path, encoded)


class Checkpoint:
    def __init__(self, project_dir: str | Path, project_id: str | None = None):
        self.project_dir = Path(project_dir)
        self.path = self.project_dir / "checkpoint.json"
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                if self.data.get("version") != CHECKPOINT_VERSION:
                    raise ValueError("Unsupported checkpoint version")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                backup = self.path.with_suffix(".corrupt.json")
                if backup.exists():
                    backup = self.path.with_name(f"checkpoint.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S%f')}.json")
                self.path.replace(backup)
                self.data = self._new(project_id)
                self.data.setdefault("errors", []).append(f"손상된 체크포인트를 보존하고 새로 시작했습니다: {exc}")
        else:
            self.data = self._new(project_id)
        self.data.setdefault("stages", {})
        self.save()

    @staticmethod
    def _new(project_id: str | None) -> dict[str, Any]:
        return {
            "version": CHECKPOINT_VERSION,
            "project_id": project_id,
            "created_at": _now(),
            "updated_at": _now(),
            "current_stage": None,
            "stages": {},
            "errors": [],
        }

    def save(self) -> None:
        self.data["updated_at"] = _now()
        atomic_write_json(self.path, self.data)

    def cached(self, name: str, signature: str, outputs: list[str | Path]) -> bool:
        stage = self.data.get("stages", {}).get(name, {})
        if stage.get("status") != "completed" or stage.get("signature") != signature:
            return False
        return all(Path(output).is_file() for output in outputs)

    def start(self, name: str, signature: str, outputs: list[str | Path] = ()) -> None:
        self.data["current_stage"] = name
        self.data["stages"][name] = {
            "status": "running",
            "signature": signature,
            "outputs": [str(Path(output)) for output in outputs],
            "started_at": _now(),
            "finished_at": None,
            "error": None,
        }
        self.save()

    def complete(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        stage = self.data["stages"].setdefault(name, {})
        stage.update({"status": "completed", "finished_at": _now(), "error": None})
        if metadata:
            stage["metadata"] = metadata
        self.data["current_stage"] = None
        self.save()

    def fail(self, name: str, error: BaseException, status: str = "failed") -> None:
        if status not in STAGE_STATUSES:
            raise ValueError(f"Invalid stage status: {status}")
        stage = self.data["stages"].setdefault(name, {})
        stage.update(
            {
                "status": status,
                "finished_at": _now(),
                "error": f"{type(error).__name__}: {error}",
            }
        )
        self.data.setdefault("errors", []).append({"stage": name, "at": _now(), "error": stage["error"]})
        self.data["current_stage"] = None
        self.save()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
