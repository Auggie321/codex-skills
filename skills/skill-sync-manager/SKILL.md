---
name: skill-sync-manager
description: Use when the user wants to safely sync one, multiple, or all local Codex skills into a local shared skills repository with secret redaction, private-file exclusions, validation, and no automatic git commit or push.
---

# Skill Sync Manager

Use this skill to copy local Codex skills into a shared repository safely.

## Core Behavior

- Sync from the local Codex skills directory, usually `%USERPROFILE%\.codex\skills` on Windows or `~/.codex/skills` on macOS/Linux.
- Sync into a repository that contains a `skills/` directory.
- Copy only shareable skill resources:
  - `SKILL.md`
  - `agents`
  - `scripts`
  - `templates`
  - `references`
  - `assets`
- Never copy private runtime content:
  - `local`
  - `reports`
  - `.env`, `.env.*` except `.env.example`
  - `sources.local.json`
  - `*.local.json`
  - caches, virtual environments, dependency folders, and VCS metadata
- Never stage, commit, push, or open a PR unless the user explicitly asks.
- After sync, run repository checks when available and summarize `git status --short`.

## Configuration

Prefer this private config file when it exists:

```text
<this skill>/local/config.json
```

The config is local-only and should not be shared:

```json
{
  "repo": "D:\\code_local\\codex-skills",
  "source_root": "C:\\Users\\you\\.codex\\skills",
  "skills": ["api-usage-monitor"],
  "all": false
}
```

`repo` can also come from the `CODEX_SKILLS_REPO` environment variable. If neither is set, use the current working directory only when it looks like a skills repository.

## Workflow

1. If the user names skills, sync exactly those names.
2. If the user asks to inspect or choose, list local skill names and compare them with repository skill names before syncing.
3. If no names are provided, use `local/config.json`. If that is missing, ask for the repo path or skill names.
4. Run the bundled script from this skill:

   ```powershell
   python scripts\sync_skills.py --skill api-usage-monitor --repo D:\code_local\codex-skills
   ```

   Use the active Python runtime. In Codex Desktop, the bundled Python path may be available from workspace dependencies.

5. Validate when the repository has these tools:

   ```powershell
   python tools\validate_skills.py skills
   python tools\check_private_skill_files.py
   python tools\run_smoke_tests.py
   ```

6. Report:
   - synced skill names
   - skipped private files/directories
   - validation results
   - changed files from `git status --short`

## Useful Commands

Sync one skill:

```powershell
python scripts\sync_skills.py --skill api-usage-monitor --repo D:\code_local\codex-skills
```

Sync several skills:

```powershell
python scripts\sync_skills.py --skill api-usage-monitor --skill webpage-to-xmind --repo D:\code_local\codex-skills
```

Sync every local skill:

```powershell
python scripts\sync_skills.py --all --repo D:\code_local\codex-skills
```

Preview:

```powershell
python scripts\sync_skills.py --skill api-usage-monitor --repo D:\code_local\codex-skills --dry-run
```
