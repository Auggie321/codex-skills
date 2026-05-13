# Codex Skills

Personal Codex skills for local use, sharing, and reuse.

## Available Skills

| Skill | Description |
| --- | --- |
| `api-usage-monitor` | Generate local API usage, balance, and quota reports without sharing secrets. |
| `skill-sync-manager` | Safely sync local Codex skills into this shared repository. |
| `webpage-to-xmind` | Convert webpages, articles, and documentation into local XMind-compatible review mind maps. |

## Install

### Option 1: Codex Interactive

Recommended. In a Codex session, ask Codex to install the skill from this repository:

```text
Use $skill-installer to install <skill-name> from https://github.com/Auggie321/codex-skills/tree/main/skills/<skill-name>
```

Example:

```text
Use $skill-installer to install webpage-to-xmind from https://github.com/Auggie321/codex-skills/tree/main/skills/webpage-to-xmind
```

Restart Codex after installation so the new skill is loaded.

### Option 2: Install A Skill Locally

Clone this repository, then copy the skill folder into your local Codex skills directory.

Windows:

```powershell
Copy-Item -Recurse .\skills\webpage-to-xmind "$env:USERPROFILE\.codex\skills\webpage-to-xmind" -Force
```

macOS/Linux:

```bash
cp -R ./skills/webpage-to-xmind ~/.codex/skills/webpage-to-xmind
```

For another skill, replace `webpage-to-xmind` with that skill folder name.

Restart Codex after installation.

## Use API Usage Monitor

Ask Codex to use the skill when you want a private local usage report:

```text
Use $api-usage-monitor to run my local API usage report and summarize anything that needs attention.
```

After installing the skill, copy its templates into the skill's private local folder and fill in your own values:

```powershell
$skill = "$env:USERPROFILE\.codex\skills\api-usage-monitor"
New-Item -ItemType Directory -Force "$skill\local" | Out-Null
Copy-Item "$skill\templates\.env.example" "$skill\local\.env"
Copy-Item "$skill\templates\sources.example.json" "$skill\local\sources.local.json"
```

Keep real credentials only in `local/.env` or your shell environment. The shared repository intentionally excludes `local/.env`, `local/sources.local.json`, and generated reports.

## Use Webpage To XMind

Ask Codex to use the skill with any webpage, article, or documentation URL:

```text
Use $webpage-to-xmind to create an XMind review map from this article: <url>
```

Codex will summarize the page into a review-friendly outline and generate a local `.xmind` file that can be opened with Xmind/XMind.

## Validate Locally

Run checks before publishing skill changes:

```powershell
python .\tools\validate_skills.py .\skills
python .\tools\check_private_skill_files.py
python .\tools\run_smoke_tests.py
```
