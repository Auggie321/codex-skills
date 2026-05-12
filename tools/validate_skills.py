#!/usr/bin/env python3
"""Validate Codex skill folders without external dependencies."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")


def parse_frontmatter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must start with YAML frontmatter")

    try:
        end = lines[1:].index("---") + 1
    except ValueError as exc:
        raise ValueError("SKILL.md frontmatter must end with ---") from exc

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata


def validate_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{skill_dir}: missing SKILL.md"]

    try:
        metadata = parse_frontmatter(skill_md)
    except ValueError as exc:
        return [f"{skill_dir}: {exc}"]

    name = metadata.get("name", "")
    description = metadata.get("description", "")

    if not name:
        errors.append(f"{skill_dir}: missing frontmatter name")
    elif not NAME_RE.fullmatch(name):
        errors.append(f"{skill_dir}: invalid skill name {name!r}")
    elif skill_dir.name != name:
        errors.append(f"{skill_dir}: folder name must match frontmatter name {name!r}")

    if not description:
        errors.append(f"{skill_dir}: missing frontmatter description")
    elif len(description.split()) < 8:
        errors.append(f"{skill_dir}: description should explain what triggers the skill")

    allowed_keys = {"name", "description"}
    extra_keys = sorted(set(metadata) - allowed_keys)
    if extra_keys:
        errors.append(f"{skill_dir}: unsupported frontmatter keys: {', '.join(extra_keys)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skills_dir", type=Path, nargs="?", default=Path("skills"))
    args = parser.parse_args()

    skills_dir = args.skills_dir
    if not skills_dir.is_dir():
        print(f"error: skills directory not found: {skills_dir}", file=sys.stderr)
        return 1

    errors: list[str] = []
    skill_dirs = sorted(path for path in skills_dir.iterdir() if path.is_dir())
    if not skill_dirs:
        errors.append(f"{skills_dir}: no skill folders found")

    for skill_dir in skill_dirs:
        errors.extend(validate_skill(skill_dir))

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Validated {len(skill_dirs)} skill folder(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

