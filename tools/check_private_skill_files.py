#!/usr/bin/env python3
"""Fail if private skill runtime files are tracked or present in shared paths."""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATTERNS = [
    "skills/*/local",
    "skills/*/local/*",
    "skills/*/local/**",
    "skills/*/sources.local.json",
    "skills/*/reports",
    "skills/*/reports/*",
    "skills/*/reports/**",
    ".env",
    ".env.*",
    "skills/*/.env",
    "skills/*/.env.*",
    "skills/*/**/.env",
    "skills/*/**/.env.*",
]
ALLOWED_PATTERNS = [
    ".env.example",
    "skills/*/templates/.env.example",
    "skills/*/**/.env.example",
]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_-]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{16,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".xmind",
}


def normalized(path: Path | str) -> str:
    return str(path).replace("\\", "/").strip("/")


def is_allowed(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in ALLOWED_PATTERNS)


def is_private(path: str) -> bool:
    if is_allowed(path):
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in PRIVATE_PATTERNS)


def tracked_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    return [normalized(line) for line in result.stdout.splitlines() if line.strip()]


def present_private_files() -> list[str]:
    if not (ROOT / "skills").exists():
        return []
    matches: list[str] = []
    for path in (ROOT / "skills").rglob("*"):
        if path.is_file():
            rel = normalized(path.relative_to(ROOT))
            if is_private(rel):
                matches.append(rel)
    return matches


def candidate_text_files() -> list[Path]:
    roots = [ROOT / "skills", ROOT / "tools", ROOT / "README.md", ROOT / ".github"]
    paths: list[Path] = []
    for root in roots:
        if root.is_file():
            paths.append(root)
        elif root.is_dir():
            paths.extend(path for path in root.rglob("*") if path.is_file())
    return paths


def secret_like_files() -> list[str]:
    matches: list[str] = []
    for path in candidate_text_files():
        if path.suffix.lower() in BINARY_EXTENSIONS:
            continue
        rel = normalized(path.relative_to(ROOT))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                matches.append(rel)
                break
    return matches


def main() -> int:
    tracked = [path for path in tracked_files() if is_private(path)]
    present = present_private_files()
    private_errors = sorted(set(tracked + present))
    secret_errors = sorted(set(secret_like_files()))
    if private_errors or secret_errors:
        for path in private_errors:
            print(f"error: private skill file must not be shared: {path}", file=sys.stderr)
        for path in secret_errors:
            print(f"error: secret-like value found in shared file: {path}", file=sys.stderr)
        return 1
    print("No private skill runtime files or secret-like values found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
