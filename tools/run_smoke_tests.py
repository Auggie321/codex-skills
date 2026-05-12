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


def main() -> int:
    smoke_webpage_to_xmind()
    print("Smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

