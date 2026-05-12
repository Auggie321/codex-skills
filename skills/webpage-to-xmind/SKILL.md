---
name: webpage-to-xmind
description: Convert webpage, article, documentation, or URL content into a local XMind-compatible .xmind review mind map. Use when the user asks to summarize a web page/link/site/chapter/article into an XMind mind map, create a study/review mind map from online content, or generate a .xmind file that must open in local Xmind/XMind on Windows.
---

# Webpage To XMind

## Workflow

1. Fetch the source content.
   - If the user provides a URL, browse or otherwise retrieve the page content.
   - Prefer canonical/raw source when available, such as GitHub raw Markdown for docs sites.
   - Preserve the source URL for final attribution.

2. Build a review-oriented outline.
   - Root title: concise page or chapter title.
   - First-level nodes: major concepts, chronology, frameworks, comparisons, and review prompts.
   - Child nodes: short explanatory statements, not bare headings.
   - Keep each node self-contained enough that the user does not need to constantly compare with the original page.

3. Generate the XMind file with `scripts/build_xmind_from_json.py`.
   - Create an outline JSON file in the workspace.
   - Run the script with the bundled or discovered compatible template.
   - The bundled template lives at `assets/xmind-json-v2-template.xmind` and travels with the skill across Windows, macOS, and Linux.
   - Use the resulting `.xmind` as the final artifact.

4. Validate before final response.
   - Inspect the `.xmind` ZIP entries.
   - Confirm `content.json`, `metadata.json`, `resources/`, and `manifest.json` exist.
   - Confirm `metadata.json` contains `dataStructureVersion: "2"`.
   - Confirm all ZIP entries use stored/no-compression mode.
   - Confirm `content.json` parses and the root title and first-level node count are correct.
   - If local Xmind is installed and permission is available, open the file and check logs for `not a valid XMind File`.

## Outline JSON Format

Pass this JSON shape to the script:

```json
{
  "title": "Chapter 2 Agent History",
  "source": "https://example.com/page",
  "children": [
    {
      "title": "Review thread: one sentence summary of the chapter.",
      "children": [
        {"title": "Key point: short explanation."}
      ]
    }
  ]
}
```

Only `title` is required for each node. `source` is optional and can be echoed in final attribution.

## XMind Compatibility Rules

Use `scripts/build_xmind_from_json.py`; do not hand-roll ZIP packaging unless the script is unavailable.

The script intentionally mirrors a known-good Xmind 26 JSON workbook package:

- ZIP entries: `content.json`, `metadata.json`, `resources/`, `manifest.json`
- `metadata.json`: `{"creator":{"name":"xmind-generator"},"dataStructureVersion":"2"}`
- `manifest.json`: `{"file-entries":{"content.json":{},"metadata.json":{}}}`
- ZIP method: stored/no compression
- Minimal sheet fields only: `id`, `class`, `title`, `rootTopic`
- Minimal topic fields only: `id`, `class`, `title`, optional `children`

Avoid adding optional fields unless retested locally:

- `notes`
- `markers`
- `extensions`
- `topicPositioning`
- XML workbook files such as `content.xml`, `styles.xml`, `comments.xml`
- compressed ZIP entries

## Script Usage

```powershell
& "<python.exe>" "<skill>/scripts/build_xmind_from_json.py" `
  --outline "<workspace>/outline.json" `
  --output "<workspace>/chapter-review.xmind"
```

Optional:

```powershell
--template "<path-to-known-good.xmind>"
```

If no template is supplied, the script searches common local locations for a known-good `.xmind` with the expected JSON structure, then falls back to deterministic packaging.

## Cross-Platform Notes

This skill is safe to sync to macOS and Linux. On those systems:

- Use `python3` if `python` is not available.
- Keep the skill folder intact, including `assets/xmind-json-v2-template.xmind`.
- Output paths should be platform-native, for example `~/Dropbox/CodexSync/output/page-review.xmind`.
- The generated `.xmind` format is not Windows-specific; it is the JSON v2 package shape accepted by modern Xmind.
