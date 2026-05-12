#!/usr/bin/env python3
"""Build a local-Xmind-compatible .xmind file from a review outline JSON.

This script favors Xmind 26's known-good JSON package shape:
content.json, metadata.json, resources/, manifest.json, stored without compression.
When a compatible template exists, it preserves the template's ZIP metadata and
replaces content.json in-place when possible.
"""

from __future__ import annotations

import argparse
import binascii
import json
import os
import struct
import uuid
import zipfile
from pathlib import Path
from typing import Any


METADATA = {"creator": {"name": "xmind-generator"}, "dataStructureVersion": "2"}
MANIFEST = {"file-entries": {"content.json": {}, "metadata.json": {}}}
ZIP_ENTRIES = ["content.json", "metadata.json", "resources/", "manifest.json"]


def uid() -> str:
    return str(uuid.uuid4())


def topic(node: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": uid(),
        "class": "topic",
        "title": str(node["title"]),
    }
    children = node.get("children") or []
    if children:
        out["children"] = {"attached": [topic(child) for child in children]}
    return out


def content_from_outline(outline: dict[str, Any]) -> list[dict[str, Any]]:
    title = str(outline["title"])
    root = topic({"title": title, "children": outline.get("children") or []})
    return [{
        "id": uid(),
        "class": "sheet",
        "title": title,
        "rootTopic": root,
    }]


def read_json(zf: zipfile.ZipFile, name: str) -> Any | None:
    try:
        return json.loads(zf.read(name).decode("utf-8"))
    except Exception:
        return None


def is_compatible_template(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = [i.filename for i in zf.infolist()]
            if names != ["content.json", "metadata.json", "resources/", "manifest.json"]:
                return False
            if read_json(zf, "metadata.json") != METADATA:
                return False
            if read_json(zf, "manifest.json") != MANIFEST:
                return False
            return all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())
    except Exception:
        return False


def common_template_candidates() -> list[Path]:
    home = Path.home()
    cwd = Path.cwd()
    skill_dir = Path(__file__).resolve().parents[1]
    bundled_template = skill_dir / "assets" / "xmind-json-v2-template.xmind"
    roots = [
        cwd,
        home / "Desktop",
        home / "Documents",
    ]
    results: list[Path] = []
    if bundled_template.exists():
        results.append(bundled_template)
    for root in roots:
        if root.exists():
            try:
                results.extend(root.rglob("*.xmind"))
            except Exception:
                pass
    return results


def dos_time_date() -> tuple[int, int]:
    # Fixed timestamp keeps output deterministic and avoids platform-specific ZipInfo defaults.
    return 0, 33  # 1980-01-01 00:00:00


def write_exact_stored_zip(output: Path, entries: list[tuple[str, bytes, int]]) -> None:
    """Write a minimal stored ZIP with exact Xmind-compatible external attributes."""
    chunks: list[bytes] = []
    central: list[bytes] = []
    offset = 0
    mod_time, mod_date = dos_time_date()

    for name, data, external_attr in entries:
        name_bytes = name.encode("utf-8")
        crc = binascii.crc32(data) & 0xFFFFFFFF
        local = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,  # local file header signature
            20,          # version needed
            0,           # general purpose bit flag
            0,           # stored
            mod_time,
            mod_date,
            crc,
            len(data),
            len(data),
            len(name_bytes),
            0,           # extra length
        ) + name_bytes
        chunks.append(local)
        chunks.append(data)

        central.append(struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,  # central file header signature
            20,          # version made by, MS-DOS style
            20,          # version needed
            0,
            0,
            mod_time,
            mod_date,
            crc,
            len(data),
            len(data),
            len(name_bytes),
            0,           # extra length
            0,           # comment length
            0,           # disk number
            0,           # internal attr
            external_attr,
            offset,
        ) + name_bytes)
        offset += len(local) + len(data)

    central_start = offset
    central_blob = b"".join(central)
    chunks.append(central_blob)
    end = struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        0,
        0,
        len(entries),
        len(entries),
        len(central_blob),
        central_start,
        0,
    )
    chunks.append(end)
    output.write_bytes(b"".join(chunks))


def write_fallback(output: Path, content_bytes: bytes) -> None:
    write_exact_stored_zip(output, [
        ("content.json", content_bytes, 0),
        ("metadata.json", json.dumps(METADATA, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 0),
        ("resources/", b"", 0x10),
        ("manifest.json", json.dumps(MANIFEST, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 0),
    ])


def patch_template(template: Path, output: Path, content_bytes: bytes) -> bool:
    raw = bytearray(template.read_bytes())
    with zipfile.ZipFile(template) as zf:
        info = zf.getinfo("content.json")
        if info.compress_type != zipfile.ZIP_STORED:
            return False
        if len(content_bytes) > info.file_size:
            return False
        padded = content_bytes + (b" " * (info.file_size - len(content_bytes)))
        crc = binascii.crc32(padded) & 0xFFFFFFFF

        local_offset = info.header_offset
        if raw[local_offset:local_offset + 4] != b"PK\x03\x04":
            return False
        name_len, extra_len = struct.unpack_from("<HH", raw, local_offset + 26)
        data_offset = local_offset + 30 + name_len + extra_len
        raw[data_offset:data_offset + info.file_size] = padded
        struct.pack_into("<I", raw, local_offset + 14, crc)

        cursor = 0
        patched = False
        while True:
            idx = raw.find(b"PK\x01\x02", cursor)
            if idx < 0:
                break
            fn_len, ex_len, comment_len = struct.unpack_from("<HHH", raw, idx + 28)
            name = raw[idx + 46:idx + 46 + fn_len].decode("utf-8")
            if name == "content.json":
                struct.pack_into("<I", raw, idx + 16, crc)
                patched = True
                break
            cursor = idx + 46 + fn_len + ex_len + comment_len
        if not patched:
            return False
    output.write_bytes(raw)
    return True


def validate(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"Bad ZIP member: {bad}")
        infos = zf.infolist()
        names = [i.filename for i in infos]
        if names != ZIP_ENTRIES:
            raise RuntimeError(f"Unexpected ZIP entries: {names}")
        if read_json(zf, "metadata.json") != METADATA:
            raise RuntimeError("metadata.json is not Xmind JSON v2 metadata")
        if read_json(zf, "manifest.json") != MANIFEST:
            raise RuntimeError("manifest.json does not match known-good structure")
        if any(i.compress_type != zipfile.ZIP_STORED for i in infos):
            raise RuntimeError("All ZIP entries must be stored without compression")
        content = read_json(zf, "content.json")
        if not isinstance(content, list) or not content:
            raise RuntimeError("content.json must be a non-empty sheet list")
        sheet = content[0]
        root = sheet["rootTopic"]
        first_level = root.get("children", {}).get("attached", [])
        return {
            "entries": names,
            "title": sheet["title"],
            "rootTitle": root["title"],
            "firstLevelCount": len(first_level),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--template", type=Path)
    args = parser.parse_args()

    outline = json.loads(args.outline.read_text(encoding="utf-8"))
    content = content_from_outline(outline)
    content_bytes = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    candidates = []
    if args.template:
        candidates.append(args.template)
    candidates.extend(common_template_candidates())

    used_template = None
    for candidate in candidates:
        if candidate.resolve() == args.output.resolve():
            continue
        if candidate.exists() and is_compatible_template(candidate):
            if patch_template(candidate, tmp, content_bytes):
                used_template = candidate
                break

    if used_template is None:
        write_fallback(tmp, content_bytes)

    validate(tmp)
    os.replace(tmp, args.output)
    result = validate(args.output)
    result["output"] = str(args.output)
    result["template"] = str(used_template) if used_template else None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
