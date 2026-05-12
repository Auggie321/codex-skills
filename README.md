# Codex Skills

Personal Codex skills intended for local use, sharing, and cross-platform reuse.

## Skills

- `webpage-to-xmind`: Convert webpages, articles, and documentation into local XMind-compatible review mind maps.

## Validate Locally

Run the repository checks before publishing:

```powershell
python .\tools\validate_skills.py .\skills
python .\tools\run_smoke_tests.py
```

You can also validate a single skill with Codex's local skill validator:

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" .\skills\webpage-to-xmind
```

On macOS or Linux, use `python3` if `python` is not available.

## Install A Skill Locally

Windows:

```powershell
Copy-Item -Recurse .\skills\webpage-to-xmind "$env:USERPROFILE\.codex\skills\webpage-to-xmind" -Force
```

macOS/Linux:

```bash
cp -R ./skills/webpage-to-xmind ~/.codex/skills/webpage-to-xmind
```

After installing, start a new Codex session and try:

```text
Use $webpage-to-xmind to create an XMind review map from this article: <url>
```

