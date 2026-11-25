"""run manifests: what is needed to regenerate a result (spec 0A.5, ADR 0011).

a manifest names the code (git commit, and whether the tree had uncommitted changes), the
config and its hash, the settings without secrets, the sha256 of every input file, and the
Python and package versions.
"""

import hashlib
import json
import platform
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from exga.settings import Settings

PACKAGES = ("exga", "numpy", "scipy", "pydantic", "pymupdf", "rapidfuzz", "httpx")
_CHUNK = 1 << 20


@dataclass(frozen=True)
class GitState:
    """the commit a result was made with; None where git or the repository is unavailable."""

    commit: str | None
    dirty: bool | None


def content_hash(data: object) -> str:
    """sha256 of data as canonical JSON (sorted keys), so equal content hashes equally."""
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """sha256 of a file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(repo: Path) -> GitState:
    """the HEAD commit of repo and whether its tree differs from it."""
    try:
        commit = _git(repo, "rev-parse", "HEAD")
        changes = _git(repo, "status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return GitState(commit=None, dirty=None)
    return GitState(commit=commit, dirty=bool(changes))


def package_versions(names: tuple[str, ...] = PACKAGES) -> dict[str, str | None]:
    """the installed version of each package, None when it is not installed."""
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return versions


def build_manifest(
    *,
    config: Mapping[str, object],
    settings: Settings,
    inputs: Mapping[str, Path],
    extra: Mapping[str, object],
    repo: Path,
    at: datetime,
) -> dict[str, object]:
    """the manifest of one run; extra adds run-specific entries such as model ids and seeds."""
    git = git_state(repo)
    return {
        "created_at": at.isoformat(),
        "git": {"commit": git.commit, "dirty": git.dirty},
        "config": dict(config),
        "config_hash": content_hash(config),
        # secrets never enter a manifest, which is meant to be shared with results
        "settings": settings.model_dump(mode="json", exclude={"hosted": {"api_key"}}),
        "inputs": {
            name: {"path": str(path), "sha256": file_sha256(path)} for name, path in inputs.items()
        },
        "python": platform.python_version(),
        "packages": package_versions(),
        **extra,
    }


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()
