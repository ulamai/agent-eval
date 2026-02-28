from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


def _read_hash(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _detect_git_commit(cwd: str | Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
            timeout=2,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.decode("utf-8", errors="replace").strip()
    return value or None


def capture_environment_metadata(project_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(project_root) if project_root is not None else Path.cwd()
    lock_candidates = ["poetry.lock", "requirements.txt", "pyproject.toml"]
    dependency_lock_hash = None
    for candidate in lock_candidates:
        hashed = _read_hash(root / candidate)
        if hashed:
            dependency_lock_hash = hashed
            break

    return {
        "python_version": sys.version.split(" ")[0],
        "python_implementation": platform.python_implementation(),
        "platform": sys.platform,
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "executable": sys.executable,
        "cwd": str(root),
        "git_commit": _detect_git_commit(root),
        "dependency_lock_hash": dependency_lock_hash,
        "env": {
            "PATH_hash": hashlib.sha256(os.environ.get("PATH", "").encode("utf-8")).hexdigest(),
        },
    }


def compare_environment_pins(
    pinned: dict[str, Any], current: dict[str, Any], keys: list[str] | None = None
) -> list[dict[str, Any]]:
    selected_keys = keys or [
        "python_version",
        "platform",
        "machine",
        "git_commit",
        "dependency_lock_hash",
        "container_image",
        "prompt_hash",
        "policy_hash",
    ]
    mismatches: list[dict[str, Any]] = []
    for key in selected_keys:
        pinned_value = pinned.get(key)
        if pinned_value in (None, "", {}):
            continue
        current_value = current.get(key)
        if pinned_value != current_value:
            mismatches.append(
                {"key": key, "pinned": pinned_value, "current": current_value}
            )
    return mismatches
