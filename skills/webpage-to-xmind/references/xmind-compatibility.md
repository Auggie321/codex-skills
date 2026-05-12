# XMind Compatibility Notes

Known-good local Xmind 26 JSON workbook structure:

- ZIP entries, in order: `content.json`, `metadata.json`, `resources/`, `manifest.json`
- Entries are stored without compression.
- `metadata.json` is exactly `{"creator":{"name":"xmind-generator"},"dataStructureVersion":"2"}`.
- `manifest.json` is exactly `{"file-entries":{"content.json":{},"metadata.json":{}}}`.
- `content.json` is a JSON list of sheets.
- Each sheet uses minimal keys: `id`, `class`, `title`, `rootTopic`.
- Each topic uses minimal keys: `id`, `class`, `title`, optional `children`.

Avoid adding optional fields unless retested locally:

- `notes`
- `markers`
- `extensions`
- `topicPositioning`
- XML workbook entries such as `content.xml`, `styles.xml`, `comments.xml`
- compressed ZIP entries

If Xmind reports `not a valid XMind File`, compare the produced file to a known-good file with Python `zipfile` and check entry names, compression method, metadata, manifest, and content JSON shape.
