#!/usr/bin/env python3
"""Run lightweight functional checks for bundled skills."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def smoke_webpage_to_xmind() -> None:
    skill_dir = ROOT / "skills" / "webpage-to-xmind"
    script = skill_dir / "scripts" / "build_xmind_from_json.py"
    outline = ROOT / "tests" / "fixtures" / "webpage_to_xmind_outline.json"

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "sample-review.xmind"
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--outline",
                str(outline),
                "--output",
                str(output),
            ],
            check=True,
        )

        with zipfile.ZipFile(output) as zf:
            names = [info.filename for info in zf.infolist()]
            expected = ["content.json", "metadata.json", "resources/", "manifest.json"]
            if names != expected:
                raise AssertionError(f"unexpected xmind entries: {names!r}")
            if any(info.compress_type != zipfile.ZIP_STORED for info in zf.infolist()):
                raise AssertionError("xmind entries must use stored/no-compression mode")

            metadata = json.loads(zf.read("metadata.json").decode("utf-8"))
            if metadata.get("dataStructureVersion") != "2":
                raise AssertionError("metadata.json must use dataStructureVersion 2")

            content = json.loads(zf.read("content.json").decode("utf-8"))
            root_title = content[0]["rootTopic"]["title"]
            if root_title != "Sample Article Review":
                raise AssertionError(f"unexpected root title: {root_title!r}")


def smoke_api_usage_monitor() -> None:
    skill_dir = ROOT / "skills" / "api-usage-monitor"
    script = skill_dir / "scripts" / "usage_report.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config = tmp_path / "sources.json"
        report = tmp_path / "report.md"
        details = tmp_path / "details.md"
        config.write_text(
            json.dumps(
                {
                    "report": {"title": "API Usage Monitor Smoke Test"},
                    "sources": [
                        {
                            "name": "Disabled source",
                            "provider": "deepseek_balance",
                            "enabled": False,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        subprocess.run(
            [
                sys.executable,
                str(script),
                "--config",
                str(config),
                "--out",
                str(report),
                "--details-out",
                str(details),
            ],
            check=True,
        )

        summary = report.read_text(encoding="utf-8")
        detail_text = details.read_text(encoding="utf-8")
        if "Disabled source" not in summary or "disabled" not in summary:
            raise AssertionError("api usage summary did not include disabled source")
        if "API Usage Monitor Smoke Test Details" not in detail_text:
            raise AssertionError("api usage details title was not rendered")


def smoke_skill_sync_manager() -> None:
    skill_dir = ROOT / "skills" / "skill-sync-manager"
    script = skill_dir / "scripts" / "sync_skills.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source_root = tmp_path / "source" / "skills"
        repo = tmp_path / "repo"
        local_skill = source_root / "sample-skill"
        local_skill_local = local_skill / "local"
        local_skill_templates = local_skill / "templates"
        local_skill_scripts = local_skill / "scripts"
        local_skill_templates.mkdir(parents=True)
        local_skill_scripts.mkdir()
        local_skill_local.mkdir()
        (repo / "skills").mkdir(parents=True)
        (local_skill / "SKILL.md").write_text(
            "---\n"
            "name: sample-skill\n"
            "description: Use when testing safe skill synchronization behavior.\n"
            "---\n"
            "\n"
            "# Sample Skill\n",
            encoding="utf-8",
        )
        token_like_placeholder = "sk-" + "EXAMPLE_PLACEHOLDER_TOKEN"
        (local_skill_templates / ".env.example").write_text(f"API_KEY={token_like_placeholder}\n", encoding="utf-8")
        (local_skill_scripts / "tool.py").write_text("print('hello')\n", encoding="utf-8")
        private_token = "sk-" + "real-secret-that-must-not-copy"
        (local_skill_local / ".env").write_text(f"API_KEY={private_token}\n", encoding="utf-8")

        subprocess.run(
            [
                sys.executable,
                str(script),
                "--skill",
                "sample-skill",
                "--source-root",
                str(source_root),
                "--repo",
                str(repo),
                "--no-validate",
            ],
            check=True,
        )

        copied = repo / "skills" / "sample-skill"
        if not (copied / "SKILL.md").exists():
            raise AssertionError("sample skill was not copied")
        if (copied / "local").exists():
            raise AssertionError("private local directory was copied")
        env_example = (copied / "templates" / ".env.example").read_text(encoding="utf-8")
        if "sk-" in env_example:
            raise AssertionError("example token was not redacted")


def main() -> int:
    smoke_webpage_to_xmind()
    smoke_api_usage_monitor()
    smoke_skill_sync_manager()
    print("Smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
