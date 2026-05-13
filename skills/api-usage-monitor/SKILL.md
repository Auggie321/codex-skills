---
name: api-usage-monitor
description: Use when the user wants to run, configure, or interpret a local API usage and billing monitor for providers such as DeepSeek, GitHub billing, Gemini/Google Cloud, OpenAI-compatible services, or generic HTTP JSON usage endpoints. This skill helps generate daily usage reports from local .env secrets without exposing API keys or token values, and can support Codex automations that summarize the latest report.
---

# API Usage Monitor

Use this skill to run and maintain a local API usage report without exposing secrets.

## Safety Rules

- Never print `.env` contents, API keys, bearer tokens, authorization headers, or raw URLs that contain secrets.
- Treat `local/.env`, `local/sources.local.json`, and generated reports as private local files.
- Prefer environment-variable references such as `DEEPSEEK_API_KEY` over literal secret values in config.
- If an error response might include a secret, summarize it instead of pasting raw output.

## Skill Layout

This skill owns its monitor code and private runtime files:

```text
%USERPROFILE%\.codex\skills\api-usage-monitor\
  SKILL.md
  agents\openai.yaml
  scripts\usage_report.py
  templates\.env.example
  templates\sources.example.json
  local\.env
  local\sources.local.json
  local\reports\report.md
  local\reports\details.md
```

## Run Report

Run the bundled monitor script directly from the skill directory:

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "$env:USERPROFILE\.codex\skills\api-usage-monitor\scripts\usage_report.py"
```

Then read:

```text
%USERPROFILE%\.codex\skills\api-usage-monitor\local\reports\report.md
%USERPROFILE%\.codex\skills\api-usage-monitor\local\reports\details.md
```

Summarize provider status, usage, cost, balance, warnings, and setup-needed items. Do not include secrets. `report.md` is the primary dashboard and contains only the summary table; `details.md` contains provider notes and detailed fields in plain Markdown.

The built-in provider `codex_current_usage` reads local Codex Desktop session logs and reports "Rate limits remaining" from the latest available `codex` rate-limit snapshot. It does not need an API key. Treat it as a best-effort local snapshot, not authoritative billing or exact quota accounting.

## Configure Sources

Use these local files:

- `local/.env`: private credentials and account identifiers.
- `local/sources.local.json`: private provider-specific config. Providers are enabled by default; set `enabled` to `false` only for sources the user does not want to report.
- `templates/sources.example.json`: shareable template.
- `templates/.env.example`: shareable environment template.

The `.env` files include inline comments for common confusing fields:

- `GITHUB_USERNAME`: GitHub login for personal Copilot premium request usage.
- `GITHUB_ORG`: optional organization slug from `github.com/orgs/<slug>`; leave empty for personal-only GitHub usage.
- `GITHUB_COPILOT_PREMIUM_REQUEST_ALLOWANCE`: monthly included premium request allowance used to calculate the Settings > Copilot usage percentage; defaults to 300 for Copilot Pro.
- `GOOGLE_CLOUD_PROJECT`: Google Cloud project id that owns Gemini/Vertex traffic.
- `GOOGLE_APPLICATION_CREDENTIALS`: full path to a Google service account key JSON file; recommended for server automation.
- `GOOGLE_OAUTH_ACCESS_TOKEN`: optional short-lived OAuth token with Cloud Monitoring read access, for example from `gcloud auth print-access-token`.
- `TOTAL_BUDGET`: Gemini prepaid/monthly budget used to calculate remaining balance.
- `GEMINI_BQ_PROJECT`: BigQuery project containing the Cloud Billing export table.
- `GEMINI_BQ_DATASET`: BigQuery dataset containing the Cloud Billing export table.
- `GEMINI_BILLING_TABLE`: Cloud Billing export table id.
- `GEMINI_BQ_SERVICE_FILTER`: optional regex for filtering billing rows; leave empty when the export table/dataset already represents Gemini usage.
- `CODEX_HOME`: optional local Codex data directory; leave blank to use `%USERPROFILE%\.codex`.

For Gemini prepaid balance, prefer the built-in `google_bigquery_billing_budget` provider. It queries BigQuery Cloud Billing export with the service account JSON, sums current-month net cost, and reports remaining balance against `TOTAL_BUDGET`. The service account needs BigQuery Job User on `GEMINI_BQ_PROJECT` and BigQuery Data Viewer on the billing export dataset.

When helping the user configure a new provider:

1. Add only env var names to `local/sources.local.json`.
2. Add placeholder env vars to `templates/.env.example` when the provider should be shareable.
3. Keep `local/.env` user-owned; do not overwrite it unless the user explicitly asks.
4. Use `generic_http_json` for providers with changing usage endpoints.
5. Default new providers to `enabled: true`; users can opt out by manually setting `enabled: false`.
6. For optional account-level sources, support hiding a skipped source when the account env var is empty instead of reporting setup failure.

## Automation Guidance

For personal reminders, use a Codex heartbeat or cron automation that runs the monitor and summarizes `local/reports/report.md`. Read `local/reports/details.md` only when detailed provider notes are needed.

Do not package the user's automation schedule or credentials into a shared version of the skill. Shared users should create their own automation and fill their own `local/.env`.
