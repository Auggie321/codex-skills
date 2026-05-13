#!/usr/bin/env python3
"""Safely sync local Codex skills into a shared skills repository."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SKILL_DIR / "local" / "config.json"
VALID_SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
SHAREABLE_ITEMS = ("SKILL.md", "agents", "scripts", "templates", "references", "assets")
PRIVATE_DIRS = {
    "local",
    "reports",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
}
BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".xmind"}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9_-]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{16,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
REDACTIONS = (
    re.compile(
        r"(?im)^(?P<key>[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*\s*=\s*)"
        r"(?:sk-[A-Za-z0-9][A-Za-z0-9_-]{8,}|github_pat_[A-Za-z0-9_]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|AIza[A-Za-z0-9_-]{20,})"
    ),
)


@dataclass
class SyncResult:
    synced: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync local Codex skills into a shared repository.")
    parser.add_argument("--skill", action="append", default=[], help="Skill name to sync. Repeat for multiple skills.")
    parser.add_argument("--all", action="store_true", help="Sync all local skills with SKILL.md.")
    parser.add_argument("--repo", type=Path, default=None, help="Repository root containing skills/.")
    parser.add_argument("--source-root", type=Path, default=None, help="Local Codex skills root.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Private sync config JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files.")
    parser.add_argument("--no-validate", action="store_true", help="Skip repository validation commands.")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def default_source_root() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".codex" / "skills"
    return Path.home() / ".codex" / "skills"


def resolve_repo(args: argparse.Namespace, config: dict[str, Any]) -> Path:
    value = args.repo or config.get("repo") or os.environ.get("CODEX_SKILLS_REPO")
    if value:
        return Path(value).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if (cwd / "skills").is_dir():
        return cwd
    raise SystemExit("Repository path is required. Use --repo, CODEX_SKILLS_REPO, or local/config.json.")


def resolve_source_root(args: argparse.Namespace, config: dict[str, Any]) -> Path:
    value = args.source_root or config.get("source_root")
    return Path(value).expanduser().resolve() if value else default_source_root().resolve()


def selected_skills(args: argparse.Namespace, config: dict[str, Any], source_root: Path) -> list[str]:
    explicit = list(args.skill)
    config_skills = config.get("skills", [])
    use_all = args.all or bool(config.get("all", False))
    if explicit and use_all:
        raise SystemExit("Use --skill or --all, not both.")
    if explicit:
        skills = explicit
    elif use_all:
        skills = sorted(path.name for path in source_root.iterdir() if (path / "SKILL.md").is_file())
    else:
        skills = list(config_skills)
    if not skills:
        raise SystemExit("No skills selected. Use --skill, --all, or local/config.json.")
    invalid = [name for name in skills if not VALID_SKILL_RE.fullmatch(name)]
    if invalid:
        raise SystemExit(f"Invalid skill name(s): {', '.join(invalid)}")
    return sorted(dict.fromkeys(skills))


def is_private_path(path: Path) -> bool:
    name = path.name.lower()
    if name in PRIVATE_DIRS:
        return True
    if name == ".env":
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    if name == "sources.local.json" or name.endswith(".local.json"):
        return True
    return False


def assert_child(parent: Path, child: Path) -> None:
    parent = parent.resolve()
    child = child.resolve()
    if parent == child:
        return
    try:
        child.relative_to(parent)
    except ValueError as exc:
        raise SystemExit(f"Refusing to write outside destination root: {child}") from exc


def sanitize_text_file(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    redacted = text
    for pattern in REDACTIONS:
        redacted = pattern.sub(r"\g<key>REPLACE_WITH_SECRET", redacted)
    if redacted != text:
        path.write_text(redacted, encoding="utf-8")
        return True
    return False


def contains_secret_like_value(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def clean_copied_tree(path: Path, result: SyncResult) -> None:
    if path.is_file():
        sanitize_text_file(path)
        return
    for item in sorted(path.rglob("*"), reverse=True):
        if is_private_path(item):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            result.skipped.append(str(item))
            continue
        if item.is_file():
            sanitize_text_file(item)


def sync_skill(source_root: Path, repo: Path, skill: str, dry_run: bool, result: SyncResult) -> None:
    source_skill = source_root / skill
    destination_skill = repo / "skills" / skill
    assert_child(source_root, source_skill)
    assert_child(repo / "skills", destination_skill)
    if not (source_skill / "SKILL.md").is_file():
        raise SystemExit(f"Skill missing SKILL.md: {source_skill}")

    print(f"Syncing {skill}")
    for item_name in SHAREABLE_ITEMS:
        source_item = source_skill / item_name
        if not source_item.exists():
            continue
        if is_private_path(source_item):
            result.skipped.append(str(source_item))
            continue
        destination_item = destination_skill / item_name
        assert_child(repo / "skills", destination_item)
        if dry_run:
            print(f"  would copy {item_name}")
            continue
        destination_skill.mkdir(parents=True, exist_ok=True)
        if destination_item.exists():
            if destination_item.is_dir():
                shutil.rmtree(destination_item)
            else:
                destination_item.unlink()
        if source_item.is_dir():
            shutil.copytree(source_item, destination_item, ignore=ignore_private)
        else:
            shutil.copy2(source_item, destination_item)
        clean_copied_tree(destination_item, result)
    result.synced.append(skill)


def ignore_private(directory: str, names: list[str]) -> set[str]:
    base = Path(directory)
    return {name for name in names if is_private_path(base / name)}


def scan_for_secrets(repo: Path) -> list[Path]:
    paths: list[Path] = []
    for root in (repo / "skills", repo / "tools", repo / ".github"):
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file())
    readme = repo / "README.md"
    if readme.exists():
        paths.append(readme)
    return [path for path in paths if contains_secret_like_value(path)]


def run_validation(repo: Path) -> list[tuple[str, int]]:
    checks = [
        ("validate_skills", [sys.executable, "tools/validate_skills.py", "skills"]),
        ("check_private_skill_files", [sys.executable, "tools/check_private_skill_files.py"]),
        ("run_smoke_tests", [sys.executable, "tools/run_smoke_tests.py"]),
    ]
    results: list[tuple[str, int]] = []
    for name, command in checks:
        if not Path(repo, command[1]).exists():
            continue
        completed = subprocess.run(command, cwd=repo)
        results.append((name, completed.returncode))
    return results


def git_status(repo: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        return "git not found"
    return completed.stdout.strip() or "clean"


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    repo = resolve_repo(args, config)
    source_root = resolve_source_root(args, config)
    skills = selected_skills(args, config, source_root)
    result = SyncResult()

    if not source_root.is_dir():
        raise SystemExit(f"Source skills directory not found: {source_root}")
    if not (repo / "skills").is_dir() and not args.dry_run:
        (repo / "skills").mkdir(parents=True, exist_ok=True)

    for skill in skills:
        sync_skill(source_root, repo, skill, args.dry_run, result)

    secret_files = [] if args.dry_run else scan_for_secrets(repo)
    if secret_files:
        for path in secret_files:
            print(f"error: secret-like value remains in shared file: {path}", file=sys.stderr)
        return 2

    validation = [] if args.no_validate or args.dry_run else run_validation(repo)

    print("")
    print("Summary")
    print(f"  repo: {repo}")
    print(f"  source: {source_root}")
    print(f"  synced: {', '.join(result.synced) or 'none'}")
    print(f"  skipped private items: {len(result.skipped)}")
    if validation:
        print("  validation:")
        for name, code in validation:
            print(f"    {name}: {'pass' if code == 0 else 'fail'}")
    print("  git status:")
    for line in git_status(repo).splitlines():
        print(f"    {line}")

    if validation and any(code != 0 for _, code in validation):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
