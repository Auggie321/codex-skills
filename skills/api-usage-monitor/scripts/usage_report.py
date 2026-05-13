#!/usr/bin/env python3
"""Collect API usage/balance data without printing local secrets."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parents[1] if SCRIPT_PATH.parent.name == "scripts" else SCRIPT_PATH.parent
LOCAL_DIR = SKILL_DIR / "local"
TEMPLATES_DIR = SKILL_DIR / "templates"
DEFAULT_ENV_PATHS = [LOCAL_DIR / ".env"]
DEFAULT_LOCAL_CONFIG = LOCAL_DIR / "sources.local.json"
DEFAULT_EXAMPLE_CONFIG = TEMPLATES_DIR / "sources.example.json"
DEFAULT_OUTPUT = LOCAL_DIR / "reports" / "report.md"
DEFAULT_DETAILS_OUTPUT = LOCAL_DIR / "reports" / "details.md"


SENSITIVE_NAME_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)


@dataclass
class SourceResult:
    name: str
    provider: str
    status: str
    usage: str = "-"
    cost: str = "-"
    balance: str = "-"
    notes: List[str] = field(default_factory=list)
    details: List[str] = field(default_factory=list)


class SecretSanitizer:
    def __init__(self) -> None:
        self._values: List[str] = []

    def add(self, name: str, value: Optional[str]) -> None:
        if not value:
            return
        if SENSITIVE_NAME_RE.search(name):
            self._values.append(value)

    def clean(self, text: Any) -> str:
        output = str(text)
        for value in sorted(self._values, key=len, reverse=True):
            if len(value) >= 4:
                output = output.replace(value, "***")
        return output


def load_dotenv(paths: Iterable[Path], sanitizer: SecretSanitizer) -> List[Path]:
    loaded: List[Path] = []
    for path in paths:
        if not path.exists():
            continue
        loaded.append(path)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
            sanitizer.add(key, os.environ.get(key))
    for key, value in os.environ.items():
        sanitizer.add(key, value)
    return loaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an API usage report.")
    parser.add_argument("--config", type=Path, default=None, help="Path to sources JSON.")
    parser.add_argument("--env", type=Path, action="append", default=[], help="Extra .env path.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help="Summary report Markdown path.")
    parser.add_argument("--details-out", type=Path, default=DEFAULT_DETAILS_OUTPUT, help="Details Markdown path.")
    parser.add_argument("--stdout", action="store_true", help="Also print the summary report.")
    return parser.parse_args()


def choose_config(path: Optional[Path]) -> Path:
    if path:
        return path
    if DEFAULT_LOCAL_CONFIG.exists():
        return DEFAULT_LOCAL_CONFIG
    return DEFAULT_EXAMPLE_CONFIG


def env_value(name: str, required: bool = True) -> Tuple[Optional[str], Optional[str]]:
    value = os.environ.get(name, "").strip()
    if required and not value:
        return None, f"Missing environment variable `{name}`."
    return value or None, None


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def period_params(period: str) -> Dict[str, str]:
    current = dt.datetime.now()
    params = {"year": str(current.year), "month": str(current.month)}
    if period == "today":
        params["day"] = str(current.day)
    return params


def format_decimal(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    try:
        return str(Decimal(str(value)).normalize())
    except (InvalidOperation, ValueError):
        return str(value)


def request_json(
    method: str,
    url: str,
    headers: Mapping[str, str],
    query: Optional[Mapping[str, str]],
    sanitizer: SecretSanitizer,
    timeout: int = 30,
) -> Tuple[Optional[Any], Optional[str]]:
    if query:
        separator = "&" if urllib.parse.urlparse(url).query else "?"
        url = url + separator + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, method=method.upper(), headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not body.strip():
                return {}, None
            return json.loads(body), None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = f"HTTP {exc.code}: {body[:600]}"
        return None, sanitizer.clean(message)
    except urllib.error.URLError as exc:
        return None, sanitizer.clean(f"Network error: {exc.reason}")
    except json.JSONDecodeError as exc:
        return None, sanitizer.clean(f"Response was not JSON: {exc}")


def request_json_body(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any],
    sanitizer: SecretSanitizer,
    timeout: int = 30,
) -> Tuple[Optional[Any], Optional[str]]:
    payload = json.dumps(body).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **dict(headers)}
    request = urllib.request.Request(url, method=method.upper(), headers=request_headers, data=payload)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            if not response_body.strip():
                return {}, None
            return json.loads(response_body), None
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        message = f"HTTP {exc.code}: {response_body[:600]}"
        return None, sanitizer.clean(message)
    except urllib.error.URLError as exc:
        return None, sanitizer.clean(f"Network error: {exc.reason}")
    except json.JSONDecodeError as exc:
        return None, sanitizer.clean(f"Response was not JSON: {exc}")


def deepseek_balance(source: Mapping[str, Any], sanitizer: SecretSanitizer) -> SourceResult:
    result = SourceResult(source["name"], "deepseek_balance", "ok")
    api_key_env = source.get("api_key_env", "DEEPSEEK_API_KEY")
    api_key, error = env_value(api_key_env)
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result

    data, error = request_json(
        "GET",
        source.get("url", "https://api.deepseek.com/user/balance"),
        {"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        None,
        sanitizer,
    )
    if error:
        result.status = "error"
        result.notes.append(error)
        return result

    is_available = data.get("is_available") if isinstance(data, dict) else None
    infos = data.get("balance_infos", []) if isinstance(data, dict) else []
    balances: List[str] = []
    for item in infos:
        currency = item.get("currency", "")
        total = format_decimal(item.get("total_balance"))
        granted = format_decimal(item.get("granted_balance"))
        topped = format_decimal(item.get("topped_up_balance"))
        if total is not None:
            balances.append(f"{total} {currency}".strip())
        if granted is not None or topped is not None:
            result.details.append(f"{currency}: granted={granted or '-'}, topped_up={topped or '-'}")

    result.balance = ", ".join(balances) if balances else "not reported"
    result.usage = "-"
    if is_available is not None:
        result.details.append(f"is_available={is_available}")
        if is_available is False:
            result.status = "warning"
            result.notes.append("DeepSeek account is not available for API use.")
    if not balances:
        result.status = "warning"
        result.notes.append("DeepSeek balance endpoint did not report a balance.")
    return result


def github_billing_usage(source: Mapping[str, Any], sanitizer: SecretSanitizer) -> SourceResult:
    result = SourceResult(source["name"], "github_billing_usage", "ok")
    account_env = source.get("account_env", "GITHUB_USERNAME")
    optional_account = bool(source.get("optional_if_missing_account", False))
    account, error = env_value(account_env, required=not optional_account)
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result
    if not account and optional_account:
        result.status = "skipped"
        result.notes.append(f"Optional source skipped because `{account_env}` is empty.")
        return result

    token_env = source.get("token_env", "GITHUB_TOKEN")
    token, error = env_value(token_env)
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result

    account_type = source.get("account_type", "user")
    if account_type == "org":
        path = f"/orgs/{urllib.parse.quote(account)}/settings/billing/usage"
    else:
        path = f"/users/{urllib.parse.quote(account)}/settings/billing/usage"
    url = source.get("base_url", "https://api.github.com").rstrip("/") + path
    query = period_params(source.get("period", "month"))
    query.update({str(k): str(v) for k, v in source.get("query", {}).items()})
    data, error = request_json(
        "GET",
        url,
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        query,
        sanitizer,
    )
    if error:
        result.status = "error"
        result.notes.append(error)
        return result

    if not isinstance(data, dict):
        result.status = "warning"
        result.notes.append("Unexpected GitHub response shape.")
        return result

    items = data.get("usageItems") or data.get("usage_items") or data.get("items") or []
    if isinstance(items, list):
        result.usage = f"{len(items)} usage item(s)"
    total_fields = [
        "total_net_amount",
        "total_gross_amount",
        "net_amount",
        "gross_amount",
        "total_cost",
        "cost",
    ]
    for key in total_fields:
        if key in data:
            result.cost = str(data[key])
            break
    if result.cost == "-" and isinstance(items, list):
        total = Decimal("0")
        found = False
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("net_amount", "gross_amount", "cost"):
                if key in item:
                    try:
                        total += Decimal(str(item[key]))
                        found = True
                        break
                    except InvalidOperation:
                        pass
        if found:
            result.cost = str(total.normalize())
    result.notes.append("GitHub billing endpoints usually report billed usage/cost, not LLM token counts.")
    preview = summarize_items(items, ("product", "sku", "quantity", "unit_type", "net_amount", "usage_at"), 5)
    result.details.extend(preview)
    return result


def github_copilot_premium_usage(source: Mapping[str, Any], sanitizer: SecretSanitizer) -> SourceResult:
    result = SourceResult(source["name"], "github_copilot_premium_usage", "ok")
    account_env = source.get("account_env", "GITHUB_USERNAME")
    optional_account = bool(source.get("optional_if_missing_account", False))
    account, error = env_value(account_env, required=not optional_account)
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result
    if not account and optional_account:
        result.status = "skipped"
        result.notes.append(f"Optional source skipped because `{account_env}` is empty.")
        return result

    token_env = source.get("token_env", "GITHUB_TOKEN")
    token, error = env_value(token_env)
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result

    account_type = source.get("account_type", "user")
    if account_type == "org":
        path = f"/organizations/{urllib.parse.quote(account)}/settings/billing/premium_request/usage"
    else:
        path = f"/users/{urllib.parse.quote(account)}/settings/billing/premium_request/usage"
    url = source.get("base_url", "https://api.github.com").rstrip("/") + path
    query = period_params(source.get("period", "month"))
    query.update({str(k): str(v) for k, v in source.get("query", {}).items()})

    data, error = request_json(
        "GET",
        url,
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": str(source.get("api_version", "2022-11-28")),
        },
        query,
        sanitizer,
    )
    if error:
        result.status = "error"
        result.notes.append(error)
        return result
    if not isinstance(data, dict):
        result.status = "warning"
        result.notes.append("Unexpected GitHub Copilot premium request response shape.")
        return result

    items = data.get("usageItems") or data.get("usage_items") or data.get("items") or []
    if not isinstance(items, list):
        result.status = "warning"
        result.notes.append("GitHub Copilot premium request response did not include usage items.")
        return result

    include_skus = {str(sku).lower() for sku in source.get("include_skus", ["Copilot Premium Request"])}
    quantity_keys = source.get(
        "quantity_keys",
        ["grossQuantity", "gross_quantity", "quantity", "netQuantity", "net_quantity"],
    )
    used = Decimal("0")
    matched = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        sku = str(item.get("sku", "")).lower()
        if include_skus and sku not in include_skus:
            continue
        quantity = first_decimal(item, quantity_keys)
        if quantity is None:
            continue
        used += quantity
        matched += 1

    allowance, allowance_note = copilot_allowance(source)
    if allowance is not None and allowance > 0:
        used_percent = (used / allowance) * Decimal("100")
        remaining_percent = max(Decimal("0"), Decimal("100") - used_percent)
        result.usage = (
            f"Premium requests used: {format_decimal_percent(used_percent)} "
            f"({format_decimal_amount(used)} / {format_decimal_amount(allowance)}), "
            f"remaining {format_decimal_percent(remaining_percent)}"
        )
        result.balance = f"included allowance: {format_decimal_amount(allowance)}"
    else:
        result.usage = f"Premium requests used: {format_decimal_amount(used)}"
        result.balance = "allowance not configured"
        result.status = "warning"
        result.notes.append("Set `GITHUB_COPILOT_PREMIUM_REQUEST_ALLOWANCE` or `included_allowance` to calculate a percentage.")

    result.notes.append("Matches the Copilot settings usage card more closely than the general GitHub billing endpoint; GitHub may delay displayed usage.")
    if allowance_note:
        result.details.append(allowance_note)
    result.details.append(f"matched_usage_items={matched}")
    result.details.extend(summarize_items(items, ("product", "sku", "quantity", "netQuantity", "grossQuantity", "usageAt", "usage_at"), 5))
    return result


def first_decimal(item: Mapping[str, Any], keys: Iterable[str]) -> Optional[Decimal]:
    for key in keys:
        if key in item:
            try:
                return Decimal(str(item[key]))
            except InvalidOperation:
                continue
    return None


def copilot_allowance(source: Mapping[str, Any]) -> Tuple[Optional[Decimal], Optional[str]]:
    allowance_env = str(source.get("allowance_env", "GITHUB_COPILOT_PREMIUM_REQUEST_ALLOWANCE"))
    env_allowance, _ = env_value(allowance_env, required=False)
    if env_allowance:
        try:
            return Decimal(env_allowance), f"allowance_source={allowance_env}"
        except InvalidOperation:
            return None, f"Invalid `{allowance_env}` value; expected a number."
    included = source.get("included_allowance")
    if included not in (None, ""):
        try:
            return Decimal(str(included)), "allowance_source=included_allowance"
        except InvalidOperation:
            return None, "`included_allowance` is not a number."
    return None, None


def format_decimal_amount(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01")).normalize()
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_decimal_percent(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.1")).normalize()
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text or '0'}%"


def summarize_items(items: Any, keys: Iterable[str], limit: int) -> List[str]:
    if not isinstance(items, list):
        return []
    lines: List[str] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        parts = []
        for key in keys:
            if key in item:
                parts.append(f"{key}={item[key]}")
        if parts:
            lines.append("; ".join(parts))
    if len(items) > limit:
        lines.append(f"... {len(items) - limit} more item(s)")
    return lines


def render_template(value: Any) -> Any:
    if isinstance(value, str):
        builtins = time_builtins()

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in builtins:
                return builtins[name]
            return os.environ.get(name, "")

        return re.sub(r"\{([A-Z0-9_]+)\}", replace, value)
    if isinstance(value, dict):
        return {k: render_template(v) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template(v) for v in value]
    return value


def time_builtins() -> Dict[str, str]:
    end = now_utc()
    start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = end.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "NOW_RFC3339": end.isoformat().replace("+00:00", "Z"),
        "START_OF_MONTH_RFC3339": start.isoformat().replace("+00:00", "Z"),
        "START_OF_DAY_RFC3339": today.isoformat().replace("+00:00", "Z"),
    }


def generic_http_json(source: Mapping[str, Any], sanitizer: SecretSanitizer) -> SourceResult:
    result = SourceResult(source["name"], "generic_http_json", "ok")
    url = render_template(source.get("url", ""))
    if not url:
        result.status = "setup_needed"
        result.notes.append("Missing `url`.")
        return result

    headers = {str(k): str(render_template(v)) for k, v in source.get("headers", {}).items()}
    bearer_env = source.get("bearer_token_env")
    if bearer_env:
        token, error = env_value(str(bearer_env), required=False)
        if not token and source.get("google_service_account_json_env"):
            token, error = google_service_account_access_token(source, sanitizer)
        if not token and not error:
            error = (
                f"Missing environment variable `{bearer_env}`. "
                "Set it to a short-lived bearer token or configure `google_service_account_json_env`."
            )
        if error:
            result.status = "setup_needed"
            result.notes.append(error)
            return result
        headers["Authorization"] = f"Bearer {token}"
    elif source.get("google_service_account_json_env"):
        token, error = google_service_account_access_token(source, sanitizer)
        if error:
            result.status = "setup_needed"
            result.notes.append(error)
            return result
        headers["Authorization"] = f"Bearer {token}"
    headers.setdefault("Accept", "application/json")
    query = render_template(source.get("query", {}))

    data, error = request_json(source.get("method", "GET"), url, headers, query, sanitizer)
    if error:
        result.status = "error"
        result.notes.append(error)
        return result

    extracted = extract_values(data, source.get("extract", []))
    if extracted:
        result.usage = ", ".join(f"{label}: {value}" for label, value in extracted)
    else:
        result.usage = "response received"
        result.notes.append("Add `extract` rules to summarize the JSON response.")
    note = source.get("notes")
    if note:
        result.notes.append(str(note))
    return result


def google_gemini_quota_usage(source: Mapping[str, Any], sanitizer: SecretSanitizer) -> SourceResult:
    result = SourceResult(source["name"], "google_gemini_quota_usage", "ok")
    project_env = str(source.get("project_env", "GOOGLE_CLOUD_PROJECT"))
    project, error = env_value(project_env)
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result

    token, error = google_bearer_token(source, sanitizer)
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result

    groups = source.get("metric_groups") or default_gemini_metric_groups()
    if not isinstance(groups, list):
        result.status = "setup_needed"
        result.notes.append("`metric_groups` must be a list.")
        return result

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    base_url = source.get("base_url", "https://monitoring.googleapis.com/v3").rstrip("/")
    interval = {
        "interval.startTime": render_template(str(source.get("start_time", "{START_OF_MONTH_RFC3339}"))),
        "interval.endTime": render_template(str(source.get("end_time", "{NOW_RFC3339}"))),
    }

    usage_parts: List[str] = []
    balance_parts: List[str] = []
    detail_count = 0
    first_error: Optional[str] = None
    for group in groups:
        if not isinstance(group, dict):
            continue
        label = str(group.get("label", "metric"))
        unit = str(group.get("unit", ""))
        usage_total, usage_series, error = google_monitoring_sum_metrics(
            base_url, project, headers, group.get("usage_metrics", []), interval, sanitizer
        )
        if error and first_error is None:
            first_error = error
        limit_total, limit_series, limit_error = google_monitoring_latest_sum_metrics(
            base_url, project, headers, group.get("limit_metrics", []), interval, sanitizer
        )
        if limit_error and first_error is None:
            first_error = limit_error

        if usage_series:
            usage_parts.append(f"{label}: {format_decimal_amount(usage_total)}{unit}")
            detail_count += usage_series
            if limit_series and limit_total > 0:
                percent = (usage_total / limit_total) * Decimal("100")
                balance_parts.append(f"{label} limit: {format_decimal_amount(limit_total)}{unit} ({format_decimal_percent(percent)} used)")
            elif limit_series:
                balance_parts.append(f"{label} limit: {format_decimal_amount(limit_total)}{unit}")

    if usage_parts:
        result.usage = ", ".join(usage_parts)
        result.balance = "; ".join(balance_parts) if balance_parts else "limits not reported"
        result.details.append(f"time_series_matched={detail_count}")
    elif first_error:
        result.status = "error"
        result.notes.append(first_error)
        if "HTTP 403" in first_error:
            result.notes.append(
                "The service account token was accepted, but Cloud Monitoring denied timeSeries.list. "
                "Grant the service account Monitoring Viewer (`roles/monitoring.viewer`) on `GOOGLE_CLOUD_PROJECT`, "
                "or point `GOOGLE_CLOUD_PROJECT` at the project that owns the Gemini API key usage."
            )
    else:
        result.status = "warning"
        result.usage = "no Gemini quota usage time series found"
        result.notes.append("No Gemini API quota usage metrics were returned for the selected project and time window.")

    result.notes.append("Uses official generativelanguage.googleapis.com quota usage metrics from Cloud Monitoring.")
    return result


def google_bigquery_billing_budget(source: Mapping[str, Any], sanitizer: SecretSanitizer) -> SourceResult:
    result = SourceResult(source["name"], "google_bigquery_billing_budget", "ok")
    total_budget, error = env_decimal(str(source.get("total_budget_env", "TOTAL_BUDGET")))
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result

    bq_project, error = env_value(str(source.get("bq_project_env", "GEMINI_BQ_PROJECT")))
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result
    dataset, error = env_value(str(source.get("dataset_env", "GEMINI_BQ_DATASET")))
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result
    table, error = env_value(str(source.get("table_env", "GEMINI_BILLING_TABLE")))
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result

    token, error = google_bearer_token(source, sanitizer)
    if error:
        result.status = "setup_needed"
        result.notes.append(error)
        return result

    usage_project, _ = env_value(str(source.get("usage_project_env", "GOOGLE_CLOUD_PROJECT")), required=False)
    service_filter, _ = env_value(str(source.get("service_filter_env", "GEMINI_BQ_SERVICE_FILTER")), required=False)
    if service_filter is None:
        service_filter = str(source.get("service_filter", "gemini|generative"))

    try:
        table_ref = bq_table_ref(bq_project, dataset, table)
    except ValueError as exc:
        result.status = "setup_needed"
        result.notes.append(str(exc))
        return result

    query = billing_budget_sql(table_ref)
    body = {
        "query": query,
        "useLegacySql": False,
        "timeoutMs": int(source.get("timeout_ms", 30000)),
        "parameterMode": "NAMED",
        "queryParameters": [
            bq_query_param("usage_project", usage_project or ""),
            bq_query_param("service_filter", service_filter or ""),
        ],
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    data, error = request_json_body(
        "POST",
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{urllib.parse.quote(bq_project)}/queries",
        headers,
        body,
        sanitizer,
        timeout=int(source.get("request_timeout", 60)),
    )
    if error:
        result.status = "error"
        result.notes.append(error)
        if "HTTP 403" in error:
            result.notes.append(
                "Grant the service account BigQuery Job User on GEMINI_BQ_PROJECT and BigQuery Data Viewer on the billing export dataset."
            )
        return result
    if not isinstance(data, dict):
        result.status = "warning"
        result.notes.append("Unexpected BigQuery response shape.")
        return result
    if data.get("jobComplete") is False:
        result.status = "warning"
        result.notes.append("BigQuery query did not complete before timeout; rerun the report or increase `timeout_ms`.")
        return result

    row = first_bq_row(data)
    if row is None:
        result.status = "warning"
        result.notes.append("BigQuery returned no billing rows for the selected period.")
        return result

    cost = row_decimal(row, 0)
    credits = row_decimal(row, 1)
    net_cost = row_decimal(row, 2)
    currency = row_value(row, 3) or str(source.get("currency", "USD"))
    rows_count = row_value(row, 4) or "0"
    remaining = total_budget - net_cost
    used_percent = (net_cost / total_budget) * Decimal("100") if total_budget > 0 else Decimal("0")
    remaining_percent = Decimal("100") - used_percent

    result.usage = (
        f"Billing used: {format_money(net_cost, currency)} / {format_money(total_budget, currency)} "
        f"({format_decimal_percent(used_percent)} used, {format_decimal_percent(remaining_percent)} remaining)"
    )
    result.balance = f"remaining: {format_money(remaining, currency)}"
    if remaining < 0:
        result.status = "warning"
        result.notes.append("Gemini billing usage is over the configured TOTAL_BUDGET.")
    result.details.append(f"gross_cost={format_money(cost, currency)}")
    result.details.append(f"credits={format_money(credits, currency)}")
    result.details.append(f"billing_rows={rows_count}")
    result.details.append(f"table={table_ref}")
    if usage_project:
        result.details.append(f"usage_project_filter={usage_project}")
    if service_filter:
        result.details.append(f"service_filter={service_filter}")
    result.notes.append("Uses BigQuery Cloud Billing export; GOOGLE_APPLICATION_CREDENTIALS is used for service-account authentication.")
    return result


def env_decimal(name: str) -> Tuple[Optional[Decimal], Optional[str]]:
    value, error = env_value(name)
    if error:
        return None, error
    try:
        return Decimal(str(value)), None
    except InvalidOperation:
        return None, f"Environment variable `{name}` must be a number."


def bq_table_ref(project: str, dataset: str, table: str) -> str:
    for label, value in (("project", project), ("dataset", dataset), ("table", table)):
        if not re.match(r"^[A-Za-z0-9_-]+$", value):
            raise ValueError(f"Invalid BigQuery {label} id `{value}`.")
    return f"`{project}.{dataset}.{table}`"


def billing_budget_sql(table_ref: str) -> str:
    return f"""
WITH line_items AS (
  SELECT
    cost,
    (SELECT COALESCE(SUM(c.amount), 0) FROM UNNEST(credits) c) AS credits,
    currency
  FROM {table_ref}
  WHERE usage_start_time >= TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MONTH)
    AND usage_start_time < CURRENT_TIMESTAMP()
    AND (@usage_project = '' OR project.id = @usage_project)
    AND (
      @service_filter = ''
      OR REGEXP_CONTAINS(LOWER(CONCAT(IFNULL(service.description, ''), ' ', IFNULL(sku.description, ''))), LOWER(@service_filter))
    )
)
SELECT
  COALESCE(SUM(cost), 0) AS gross_cost,
  COALESCE(SUM(credits), 0) AS credits,
  COALESCE(SUM(cost + credits), 0) AS net_cost,
  COALESCE(ANY_VALUE(currency), 'USD') AS currency,
  COUNT(1) AS rows_count
FROM line_items
""".strip()


def bq_query_param(name: str, value: str) -> Dict[str, Any]:
    return {
        "name": name,
        "parameterType": {"type": "STRING"},
        "parameterValue": {"value": value},
    }


def first_bq_row(data: Mapping[str, Any]) -> Optional[List[Mapping[str, Any]]]:
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    fields = rows[0].get("f") if isinstance(rows[0], dict) else None
    return fields if isinstance(fields, list) else None


def row_value(row: List[Mapping[str, Any]], index: int) -> Optional[str]:
    if index >= len(row) or not isinstance(row[index], dict):
        return None
    value = row[index].get("v")
    return str(value) if value is not None else None


def row_decimal(row: List[Mapping[str, Any]], index: int) -> Decimal:
    value = row_value(row, index)
    if value is None:
        return Decimal("0")
    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("0")


def format_money(value: Decimal, currency: str) -> str:
    quantized = value.quantize(Decimal("0.000001"))
    text = format(quantized.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text or '0'} {currency}".strip()


def google_bearer_token(source: Mapping[str, Any], sanitizer: SecretSanitizer) -> Tuple[Optional[str], Optional[str]]:
    if source.get("prefer_service_account") and source.get("google_service_account_json_env"):
        return google_service_account_access_token(source, sanitizer)
    bearer_env = source.get("bearer_token_env")
    if bearer_env:
        token, error = env_value(str(bearer_env), required=False)
        if token:
            return token, None
        if error:
            return None, error
    if source.get("google_service_account_json_env"):
        return google_service_account_access_token(source, sanitizer)
    return None, "Set `GOOGLE_OAUTH_ACCESS_TOKEN` or `GOOGLE_APPLICATION_CREDENTIALS` for Google API access."


def default_gemini_metric_groups() -> List[Dict[str, Any]]:
    prefix = "generativelanguage.googleapis.com/quota"
    return [
        {
            "label": "input tokens",
            "unit": " tokens",
            "usage_metrics": [
                f"{prefix}/generate_content_free_tier_input_token_count/usage",
                f"{prefix}/generate_content_paid_tier_input_token_count/usage",
                f"{prefix}/generate_content_paid_tier_2_input_token_count/usage",
                f"{prefix}/generate_content_paid_tier_3_input_token_count/usage",
            ],
            "limit_metrics": [
                f"{prefix}/generate_content_free_tier_input_token_count/limit",
                f"{prefix}/generate_content_paid_tier_input_token_count/limit",
                f"{prefix}/generate_content_paid_tier_2_input_token_count/limit",
                f"{prefix}/generate_content_paid_tier_3_input_token_count/limit",
            ],
        },
        {
            "label": "requests",
            "unit": " requests",
            "usage_metrics": [
                f"{prefix}/generate_content_free_tier_requests/usage",
                f"{prefix}/generate_requests_per_model/usage",
                f"{prefix}/generate_content_paid_tier_2_requests/usage",
                f"{prefix}/generate_content_paid_tier_3_requests/usage",
            ],
            "limit_metrics": [
                f"{prefix}/generate_content_free_tier_requests/limit",
                f"{prefix}/generate_requests_per_model/limit",
                f"{prefix}/generate_content_paid_tier_2_requests/limit",
                f"{prefix}/generate_content_paid_tier_3_requests/limit",
            ],
        },
    ]


def google_monitoring_sum_metrics(
    base_url: str,
    project: str,
    headers: Mapping[str, str],
    metric_types: Any,
    interval: Mapping[str, str],
    sanitizer: SecretSanitizer,
) -> Tuple[Decimal, int, Optional[str]]:
    total = Decimal("0")
    series_count = 0
    first_error: Optional[str] = None
    for metric_type in metric_types if isinstance(metric_types, list) else []:
        data, error = google_monitoring_time_series(base_url, project, headers, str(metric_type), interval, sanitizer)
        if error:
            if first_error is None:
                first_error = error
            continue
        subtotal, count = sum_time_series_points(data)
        total += subtotal
        series_count += count
    return total, series_count, first_error


def google_monitoring_latest_sum_metrics(
    base_url: str,
    project: str,
    headers: Mapping[str, str],
    metric_types: Any,
    interval: Mapping[str, str],
    sanitizer: SecretSanitizer,
) -> Tuple[Decimal, int, Optional[str]]:
    total = Decimal("0")
    series_count = 0
    first_error: Optional[str] = None
    for metric_type in metric_types if isinstance(metric_types, list) else []:
        data, error = google_monitoring_time_series(base_url, project, headers, str(metric_type), interval, sanitizer)
        if error:
            if first_error is None:
                first_error = error
            continue
        subtotal, count = latest_sum_time_series_points(data)
        total += subtotal
        series_count += count
    return total, series_count, first_error


def google_monitoring_time_series(
    base_url: str,
    project: str,
    headers: Mapping[str, str],
    metric_type: str,
    interval: Mapping[str, str],
    sanitizer: SecretSanitizer,
) -> Tuple[Optional[Any], Optional[str]]:
    query = dict(interval)
    query["filter"] = f'metric.type="{metric_type}"'
    return request_json(
        "GET",
        f"{base_url}/projects/{urllib.parse.quote(project)}/timeSeries",
        headers,
        query,
        sanitizer,
    )


def sum_time_series_points(data: Any) -> Tuple[Decimal, int]:
    total = Decimal("0")
    count = 0
    for series in data.get("timeSeries", []) if isinstance(data, dict) else []:
        if not isinstance(series, dict):
            continue
        count += 1
        for point in series.get("points", []):
            value = typed_value_decimal(point)
            if value is not None:
                total += value
    return total, count


def latest_sum_time_series_points(data: Any) -> Tuple[Decimal, int]:
    total = Decimal("0")
    count = 0
    for series in data.get("timeSeries", []) if isinstance(data, dict) else []:
        if not isinstance(series, dict):
            continue
        points = series.get("points", [])
        if not isinstance(points, list) or not points:
            continue
        value = typed_value_decimal(points[0])
        if value is not None:
            total += value
            count += 1
    return total, count


def typed_value_decimal(point: Any) -> Optional[Decimal]:
    if not isinstance(point, dict):
        return None
    value = point.get("value")
    if not isinstance(value, dict):
        return None
    for key in ("int64Value", "doubleValue", "decimalValue"):
        if key in value:
            try:
                return Decimal(str(value[key]))
            except InvalidOperation:
                return None
    return None


def google_service_account_access_token(
    source: Mapping[str, Any],
    sanitizer: SecretSanitizer,
) -> Tuple[Optional[str], Optional[str]]:
    credentials_env = str(source.get("google_service_account_json_env", "GOOGLE_APPLICATION_CREDENTIALS"))
    credentials_path, error = env_value(credentials_env)
    if error:
        return None, (
            f"Missing `{credentials_env}`. Set it to the full path of your Google service account key JSON, "
            "or set GOOGLE_OAUTH_ACCESS_TOKEN to a short-lived token."
        )
    path = Path(credentials_path).expanduser()
    if not path.exists():
        return None, f"Google service account key file was not found: `{path}`."
    try:
        credentials = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, sanitizer.clean(f"Could not read Google service account key JSON: {exc}")

    client_email = credentials.get("client_email")
    private_key = credentials.get("private_key")
    token_uri = credentials.get("token_uri") or "https://oauth2.googleapis.com/token"
    if not client_email or not private_key:
        return None, "Google service account JSON must include `client_email` and `private_key`."

    scope = str(source.get("google_oauth_scope", "https://www.googleapis.com/auth/monitoring.read"))
    now = int(now_utc().timestamp())
    try:
        assertion = make_service_account_jwt(str(client_email), str(private_key), str(token_uri), scope, now)
    except ValueError as exc:
        return None, sanitizer.clean(f"Could not create Google service account JWT: {exc}")
    sanitizer.add("GOOGLE_SERVICE_ACCOUNT_ASSERTION", assertion)

    body = urllib.parse.urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        str(token_uri),
        method="POST",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        return None, sanitizer.clean(f"Google token exchange failed with HTTP {exc.code}: {body_text[:600]}")
    except urllib.error.URLError as exc:
        return None, sanitizer.clean(f"Google token exchange network error: {exc.reason}")
    except json.JSONDecodeError as exc:
        return None, sanitizer.clean(f"Google token exchange response was not JSON: {exc}")

    access_token = data.get("access_token") if isinstance(data, dict) else None
    if not access_token:
        return None, "Google token exchange did not return an access token."
    sanitizer.add("GOOGLE_OAUTH_ACCESS_TOKEN", str(access_token))
    return str(access_token), None


def make_service_account_jwt(
    client_email: str,
    private_key_pem: str,
    token_uri: str,
    scope: str,
    now: int,
) -> str:
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": client_email,
        "scope": scope,
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = (
        b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    n, d = load_rsa_private_key(private_key_pem)
    signature = rsa_pkcs1_v15_sha256_sign(signing_input.encode("ascii"), n, d)
    return signing_input + "." + b64url(signature)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def load_rsa_private_key(pem: str) -> Tuple[int, int]:
    der = pem_to_der(pem)
    if "BEGIN PRIVATE KEY" in pem and "BEGIN RSA PRIVATE KEY" not in pem:
        der = pkcs8_private_key_payload(der)
    return rsa_private_numbers_from_der(der)


def pem_to_der(pem: str) -> bytes:
    lines = [line.strip() for line in pem.strip().splitlines() if "-----" not in line]
    return base64.b64decode("".join(lines))


def pkcs8_private_key_payload(der: bytes) -> bytes:
    value, _ = read_asn1_value(der, 0, 0x30)
    pos = 0
    _, pos = read_asn1_value(value, pos, 0x02)
    _, pos = read_asn1_value(value, pos, 0x30)
    private_key, _ = read_asn1_value(value, pos, 0x04)
    return private_key


def rsa_private_numbers_from_der(der: bytes) -> Tuple[int, int]:
    value, _ = read_asn1_value(der, 0, 0x30)
    pos = 0
    ints: List[int] = []
    while pos < len(value):
        item, pos = read_asn1_value(value, pos, 0x02)
        ints.append(int.from_bytes(item, "big", signed=False))
    if len(ints) < 4:
        raise ValueError("RSA private key did not contain modulus and private exponent.")
    return ints[1], ints[3]


def read_asn1_value(data: bytes, pos: int, expected_tag: int) -> Tuple[bytes, int]:
    if pos >= len(data) or data[pos] != expected_tag:
        actual = data[pos] if pos < len(data) else None
        raise ValueError(f"Unexpected ASN.1 tag: expected {expected_tag}, got {actual}.")
    pos += 1
    length, pos = read_asn1_length(data, pos)
    end = pos + length
    if end > len(data):
        raise ValueError("ASN.1 length extends beyond input.")
    return data[pos:end], end


def read_asn1_length(data: bytes, pos: int) -> Tuple[int, int]:
    first = data[pos]
    pos += 1
    if first < 0x80:
        return first, pos
    count = first & 0x7F
    if count == 0 or count > 4:
        raise ValueError("Unsupported ASN.1 length encoding.")
    return int.from_bytes(data[pos : pos + count], "big"), pos + count


def rsa_pkcs1_v15_sha256_sign(message: bytes, n: int, d: int) -> bytes:
    digest_info_prefix = bytes.fromhex("3031300d060960864801650304020105000420")
    digest_info = digest_info_prefix + hashlib.sha256(message).digest()
    key_size = (n.bit_length() + 7) // 8
    padding_size = key_size - len(digest_info) - 3
    if padding_size < 8:
        raise ValueError("RSA key is too small for SHA-256 PKCS#1 v1.5 signing.")
    encoded = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
    signature_int = pow(int.from_bytes(encoded, "big"), d, n)
    return signature_int.to_bytes(key_size, "big")


def codex_current_usage(source: Mapping[str, Any], sanitizer: SecretSanitizer) -> SourceResult:
    result = SourceResult(source["name"], "codex_current_usage", "ok")
    codex_home = Path(
        os.environ.get(str(source.get("codex_home_env", "CODEX_HOME")), "")
        or Path.home() / ".codex"
    )
    session_glob = str(source.get("sessions_glob", "sessions/*/*/*/rollout-*.jsonl"))
    limit_id = str(source.get("limit_id", "codex"))
    newest = latest_codex_token_count(codex_home, session_glob, limit_id)
    if newest is None:
        result.status = "setup_needed"
        result.notes.append(f"No Codex token_count event found under `{codex_home}`.")
        return result

    event_path, event = newest
    payload = event.get("payload", {}) if isinstance(event, dict) else {}
    info = payload.get("info") if isinstance(payload, dict) else None
    rate_limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(info, dict) and not isinstance(rate_limits, dict):
        result.status = "warning"
        result.notes.append("Latest Codex token_count event did not include usage details.")
        return result

    if isinstance(rate_limits, dict):
        primary = rate_limits.get("primary")
        secondary = rate_limits.get("secondary")
        parts = []
        for label, window in (("primary", primary), ("secondary", secondary)):
            if isinstance(window, dict):
                parts.append(format_codex_window(label, window))
        result.usage = "Rate limits remaining: " + (", ".join(part for part in parts if part) or "rate limit present")
        credits = rate_limits.get("credits")
        result.balance = format_codex_plan(rate_limits)
        reached = rate_limits.get("rate_limit_reached_type")
        if reached:
            result.status = "warning"
            result.notes.append(f"Rate limit reached: {reached}.")

    result.notes.append("Rate limits remaining is computed from the latest local Desktop token_count event; it is not billing data and may lag the UI.")
    timestamp = event.get("timestamp") if isinstance(event, dict) else None
    if timestamp:
        result.details.append(f"snapshot_at={timestamp}")

    if isinstance(info, dict) and source.get("include_token_details", False):
        total = info.get("total_token_usage")
        last = info.get("last_token_usage")
        if isinstance(total, dict):
            result.details.append("session total tokens: " + format_token_usage(total))
        if isinstance(last, dict):
            result.details.append("last event tokens: " + format_token_usage(last))
        if info.get("model_context_window"):
            result.details.append(f"model_context_window={info['model_context_window']}")

    result.cost = "not exposed locally"
    result.details.append(f"source_file={event_path}")
    return result


def latest_codex_token_count(
    codex_home: Path,
    session_glob: str,
    limit_id: str,
    max_files: int = 50,
) -> Optional[Tuple[Path, Mapping[str, Any]]]:
    sessions_root = codex_home / "sessions"
    if not sessions_root.exists():
        return None
    candidates = sorted(
        sessions_root.glob(session_glob.removeprefix("sessions/")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    newest_path: Optional[Path] = None
    newest_event: Optional[Mapping[str, Any]] = None
    newest_timestamp: Optional[str] = None
    for path in candidates[:max_files]:
        event = latest_token_count_in_file(path, limit_id)
        if event is not None:
            timestamp = str(event.get("timestamp", ""))
            if newest_event is None or timestamp > (newest_timestamp or ""):
                newest_path = path
                newest_event = event
                newest_timestamp = timestamp
    if newest_path is None or newest_event is None:
        return None
    return newest_path, newest_event


def latest_token_count_in_file(path: Path, limit_id: str) -> Optional[Mapping[str, Any]]:
    latest: Optional[Mapping[str, Any]] = None
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if '"token_count"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload", {}) if isinstance(event, dict) else {}
                if not isinstance(payload, dict) or payload.get("type") != "token_count":
                    continue
                rate_limits = payload.get("rate_limits")
                if isinstance(rate_limits, dict) and rate_limits.get("limit_id") not in (None, limit_id):
                    continue
                latest = event
    except OSError:
        return None
    return latest


def format_codex_window(label: str, window: Mapping[str, Any]) -> str:
    used = window.get("used_percent")
    minutes = window.get("window_minutes")
    label_text = format_codex_window_label(label, minutes)
    reset = format_codex_reset(window.get("resets_at"), minutes)
    if used is not None:
        remaining = max(0, min(100, 100 - float(used)))
        parts = [f"{label_text} {format_percent(remaining)}"]
    else:
        parts = [label_text]
    if reset:
        parts.append(reset)
    return " ".join(parts)


def format_codex_window_label(label: str, minutes: Any) -> str:
    try:
        window_minutes = int(minutes)
    except (TypeError, ValueError):
        return label
    if window_minutes == 300:
        return "5h"
    if window_minutes == 10080:
        return "Weekly"
    if window_minutes % 1440 == 0:
        days = window_minutes // 1440
        return f"{days}d"
    if window_minutes % 60 == 0:
        hours = window_minutes // 60
        return f"{hours}h"
    return f"{window_minutes}m"


def format_codex_reset(value: Any, minutes: Any) -> Optional[str]:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    reset = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).astimezone()
    try:
        window_minutes = int(minutes)
    except (TypeError, ValueError):
        window_minutes = 0
    if window_minutes >= 1440:
        return f"{reset.month}月{reset.day}日"
    return reset.strftime("%H:%M")


def format_percent(value: float) -> str:
    if value.is_integer():
        return f"{int(value)}%"
    return f"{value:.1f}%"


def format_codex_plan(rate_limits: Mapping[str, Any]) -> str:
    plan_type = rate_limits.get("plan_type")
    if plan_type:
        return f"plan: {plan_type}"
    credits = rate_limits.get("credits")
    if isinstance(credits, dict):
        if credits.get("unlimited"):
            return "subscription/unlimited"
        if credits.get("has_credits"):
            balance = credits.get("balance")
            return f"credits: {balance if balance is not None else 'available'}"
    return "no paid plan detected"


def format_token_usage(usage: Mapping[str, Any]) -> str:
    keys = [
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ]
    return ", ".join(f"{key}={usage[key]}" for key in keys if key in usage)


def extract_values(data: Any, rules: Any) -> List[Tuple[str, str]]:
    if not isinstance(rules, list):
        return []
    values: List[Tuple[str, str]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        label = str(rule.get("label", rule.get("path", "value")))
        found = get_path(data, str(rule.get("path", "")))
        rule_type = rule.get("type")
        if rule_type == "count":
            value = len(found) if isinstance(found, list) else (1 if found is not None else 0)
        elif rule_type == "sum":
            value = sum_decimal(found)
        else:
            value = compact_value(found)
        values.append((label, str(value)))
    return values


def get_path(data: Any, path: str) -> Any:
    current = data
    if not path:
        return current
    for part in path.split("."):
        if part.endswith("[]"):
            key = part[:-2]
            if isinstance(current, dict):
                current = current.get(key, [])
            if not isinstance(current, list):
                return []
            continue
        if isinstance(current, list):
            next_values = []
            for item in current:
                if isinstance(item, dict) and part in item:
                    next_values.append(item[part])
            current = next_values
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def sum_decimal(value: Any) -> str:
    values = value if isinstance(value, list) else [value]
    total = Decimal("0")
    found = False
    for item in values:
        try:
            total += Decimal(str(item))
            found = True
        except (InvalidOperation, ValueError):
            pass
    return str(total.normalize()) if found else "0"


def compact_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)
    if isinstance(value, list):
        return f"{len(value)} item(s)"
    if isinstance(value, dict):
        return f"{len(value)} field(s)"
    return str(value)


PROVIDERS = {
    "codex_current_usage": codex_current_usage,
    "deepseek_balance": deepseek_balance,
    "github_billing_usage": github_billing_usage,
    "github_copilot_premium_usage": github_copilot_premium_usage,
    "google_bigquery_billing_budget": google_bigquery_billing_budget,
    "google_gemini_quota_usage": google_gemini_quota_usage,
    "generic_http_json": generic_http_json,
}


def collect(config: Mapping[str, Any], sanitizer: SecretSanitizer) -> List[SourceResult]:
    results: List[SourceResult] = []
    sources = config.get("sources", [])
    if not isinstance(sources, list):
        return [SourceResult("config", "config", "error", notes=["`sources` must be a list."])]
    for source in sources:
        if not isinstance(source, dict):
            continue
        name = str(source.get("name", "unnamed source"))
        provider = str(source.get("provider", ""))
        if not source.get("enabled", False):
            notes = ["Set `enabled` to true in sources.local.json."]
            note = source.get("notes")
            if note:
                notes.append(str(note))
            results.append(SourceResult(name, provider or "-", "disabled", notes=notes))
            continue
        handler = PROVIDERS.get(provider)
        if not handler:
            results.append(SourceResult(name, provider, "setup_needed", notes=[f"Unknown provider `{provider}`."]))
            continue
        try:
            result = handler(source, sanitizer)
            if result.status == "skipped" and source.get("hide_when_skipped", False):
                continue
            note = source.get("notes")
            if note and str(note) not in result.notes:
                result.notes.append(str(note))
            results.append(result)
        except Exception as exc:  # Keep scheduled reports alive when one provider breaks.
            results.append(SourceResult(name, provider, "error", notes=[sanitizer.clean(exc)]))
    return results


def render_report(config_path: Path, env_paths: List[Path], results: List[SourceResult], title: str) -> str:
    return render_summary_table(results)


def render_summary_table(results: List[SourceResult]) -> str:
    lines = [
        "| Provider | Status | Usage | Cost | Balance |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in results:
        lines.append(
            "| "
            + " | ".join(
                escape_md(value)
                for value in [item.name, item.status, item.usage, item.cost, item.balance]
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_details(config_path: Path, env_paths: List[Path], results: List[SourceResult], title: str) -> str:
    generated = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        f"# {title} Details",
        "",
        f"Generated: `{generated}`",
        f"Config: `{config_path}`",
        f"Env files loaded: `{', '.join(str(p) for p in env_paths) or 'none'}`",
        "",
        "## Summary",
        "",
        render_summary_table(results).rstrip(),
        "",
    ]
    for item in results:
        lines.extend([f"## {item.name} ({item.status})", ""])
        lines.extend(
            [
                f"- Provider: `{item.provider}`",
                f"- Usage: {item.usage}",
                f"- Cost: {item.cost}",
                f"- Balance: {item.balance}",
            ]
        )
        if item.notes:
            lines.extend(["", "### Notes", ""])
            lines.extend(f"- {note}" for note in item.notes)
        if item.details:
            lines.extend(["", "### Details", ""])
            lines.extend(f"- {detail}" for detail in item.details)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def escape_md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    args = parse_args()
    sanitizer = SecretSanitizer()
    env_paths = DEFAULT_ENV_PATHS + args.env
    loaded_env = load_dotenv(env_paths, sanitizer)
    config_path = choose_config(args.config)
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 2
    config = json.loads(config_path.read_text(encoding="utf-8"))
    results = collect(config, sanitizer)
    title = str(config.get("report", {}).get("title", "API Usage Report"))
    report = sanitizer.clean(render_report(config_path, loaded_env, results, title))
    details = sanitizer.clean(render_details(config_path, loaded_env, results, title))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.details_out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    args.details_out.write_text(details, encoding="utf-8")
    if args.stdout:
        print(report)
    print(f"Wrote report: {args.out}")
    print(f"Wrote details: {args.details_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
