# API Usage Monitor

This is a small local collector for API usage and balance checks. It is designed
to be boring and easy to repair: each provider is isolated, and secrets live only
in `.env`.

## Setup

1. Copy the templates:

   ```powershell
   Copy-Item tools\api-usage-monitor\.env.example .env
   Copy-Item tools\api-usage-monitor\sources.example.json tools\api-usage-monitor\sources.local.json
   ```

2. Fill `.env` with your own keys and account names.

3. Edit `tools/api-usage-monitor/sources.local.json` and set `enabled` to `true`
   or `false` for sources you do not want. Providers are enabled by default.

4. Run:

   ```powershell
   python tools\api-usage-monitor\usage_report.py
   ```

   If `python` is not on PATH in Codex Desktop, use the bundled runtime:

   ```powershell
   & "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" tools\api-usage-monitor\usage_report.py
   ```

The Markdown reports are written to:

```text
tools/api-usage-monitor/reports/report.md
tools/api-usage-monitor/reports/details.md
```

## Secret handling

- `.env`, `*.env`, `sources.local.json`, and generated reports are ignored by git.
- `report.md` prints a compact provider summary table only; `details.md` contains provider notes and detailed fields in plain Markdown.
- Environment variable values are masked if they appear in an error response.
- Avoid putting API keys directly in `sources.local.json`; use `*_env` fields.

## Supported providers

- `codex_current_usage`: reads local Codex Desktop session JSONL files for the
  latest local "Rate limits remaining" snapshot. This requires no API key, but
  it is a best-effort Desktop log snapshot and may lag the UI.
- `deepseek_balance`: calls DeepSeek `/user/balance` and reports prepaid
  current balance; usage is not reported for this source.
- `github_copilot_premium_usage`: calls GitHub premium request usage endpoints
  for the Settings > Copilot usage card and calculates used percentage from the
  configured monthly allowance.
- `github_billing_usage`: calls GitHub billing usage endpoints for a user or org.
- `google_bigquery_billing_budget`: queries BigQuery Cloud Billing export,
  calculates current-month net cost, and subtracts it from `TOTAL_BUDGET`.
- `google_gemini_quota_usage`: calls Cloud Monitoring
  `generativelanguage.googleapis.com/quota/.../usage` metrics for Gemini API
  input token and request usage.
- `generic_http_json`: calls a configurable JSON HTTP endpoint and extracts safe
  fields. Use this for providers whose usage endpoint changes often.

## Gemini notes

Gemini API key usage is often not available by querying the API key itself.
For prepaid Gemini API balance, use BigQuery Cloud Billing export. Set
`TOTAL_BUDGET`, `GEMINI_BQ_PROJECT`, `GEMINI_BQ_DATASET`, and
`GEMINI_BILLING_TABLE`; the monitor queries current-month net cost and reports
remaining balance. The service account JSON in `GOOGLE_APPLICATION_CREDENTIALS`
avoids repeated `gcloud auth login` and needs BigQuery Job User plus BigQuery
Data Viewer access. Leave `GEMINI_BQ_SERVICE_FILTER` empty when the billing
export table already isolates Gemini usage.

For server automation, prefer a Google service account key JSON file:

- Put the JSON file somewhere local and private.
- Set `GOOGLE_APPLICATION_CREDENTIALS` to the full JSON path.
- Set `GOOGLE_CLOUD_PROJECT` to the project id that owns the Gemini/Vertex usage.
- Grant the service account Monitoring Viewer, or another role that includes
  `monitoring.timeSeries.list`.
- Keep `GOOGLE_OAUTH_ACCESS_TOKEN` empty unless you want to override with a
  one-off token from `gcloud auth print-access-token`.
