"""Token usage and cost estimation for LLM calls."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any


# Prices are per 1M tokens. Anthropic/OpenRouter examples are USD; DeepSeek
# official platform prices are CNY/RMB and include cache-hit/cache-miss input.
DEFAULT_PRICE_PER_MILLION: dict[tuple[str, str], dict[str, float | str]] = {
    ("anthropic", "claude-opus-4-6"): {
        "currency": "USD",
        "input": 15.0,
        "output": 75.0,
    },
    ("openrouter", "anthropic/claude-opus-4-6"): {
        "currency": "USD",
        "input": 15.0,
        "output": 75.0,
    },
    ("deepseek", "deepseek-v4-flash"): {
        "currency": "CNY",
        "input_cache_hit": 0.02,
        "input_cache_miss": 1.0,
        "output": 2.0,
    },
    ("deepseek", "deepseek-v4-pro"): {
        "currency": "CNY",
        "input_cache_hit": 0.025,
        "input_cache_miss": 3.0,
        "output": 6.0,
    },
    ("ollama", "qwen3:8b"): {
        "currency": "USD",
        "input": 0.0,
        "output": 0.0,
    },
    ("mock", "mock-prose"): {"currency": "USD", "input": 0.0, "output": 0.0},
    ("mock", "mock-critic"): {"currency": "USD", "input": 0.0, "output": 0.0},
    ("mock", "mock-summary"): {"currency": "USD", "input": 0.0, "output": 0.0},
    ("mock", "mock-ai-flavor"): {"currency": "USD", "input": 0.0, "output": 0.0},
    ("mock", "mock-assist"): {"currency": "USD", "input": 0.0, "output": 0.0},
    ("mock", "mock-revise"): {"currency": "USD", "input": 0.0, "output": 0.0},
}


def estimate_tokens(text: str) -> int:
    """Cheap mixed Chinese/English token estimate when provider usage is unavailable."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = max(0, len(text) - cjk)
    return max(1, math.ceil(cjk * 0.75 + other / 4))


def usage_from_text(input_text: str, output_text: str = "") -> dict[str, int | str]:
    input_tokens = estimate_tokens(input_text)
    output_tokens = estimate_tokens(output_text)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "input_cache_hit_tokens": 0,
        "input_cache_miss_tokens": input_tokens,
        "token_source": "estimated",
    }


def usage_from_provider(raw_usage: Any, input_text: str = "", output_text: str = "") -> dict[str, int | str]:
    if raw_usage is None:
        return usage_from_text(input_text, output_text)
    getter = _usage_getter(raw_usage)
    input_tokens = _first_int(
        getter("input_tokens"),
        getter("prompt_tokens"),
        getter("prompt_eval_count"),
    )
    output_tokens = _first_int(
        getter("output_tokens"),
        getter("completion_tokens"),
        getter("eval_count"),
    )
    total_tokens = _first_int(getter("total_tokens"))
    hit_tokens = _first_int(
        getter("prompt_cache_hit_tokens"),
        getter("input_cache_hit_tokens"),
        getter("cache_hit_tokens"),
    )
    miss_tokens = _first_int(
        getter("prompt_cache_miss_tokens"),
        getter("input_cache_miss_tokens"),
        getter("cache_miss_tokens"),
    )

    prompt_details = getter("prompt_tokens_details") or getter("input_tokens_details")
    cached_tokens = _nested_int(prompt_details, "cached_tokens")
    if hit_tokens == 0 and cached_tokens:
        hit_tokens = cached_tokens

    if input_tokens == 0 and (hit_tokens or miss_tokens):
        input_tokens = hit_tokens + miss_tokens
    if miss_tokens == 0 and input_tokens > hit_tokens:
        miss_tokens = input_tokens - hit_tokens
    if total_tokens == 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    if input_tokens == 0 and output_tokens == 0 and total_tokens == 0:
        return usage_from_text(input_text, output_text)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "input_cache_hit_tokens": hit_tokens,
        "input_cache_miss_tokens": miss_tokens,
        "token_source": "provider",
    }


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    input_cache_hit_tokens: int = 0,
    input_cache_miss_tokens: int | None = None,
) -> dict[str, Any]:
    plan = price_plan(provider, model)
    input_tokens = max(0, int(input_tokens or 0))
    output_tokens = max(0, int(output_tokens or 0))
    hit_tokens = max(0, int(input_cache_hit_tokens or 0))
    if input_cache_miss_tokens is None:
        miss_tokens = max(0, input_tokens - hit_tokens) if hit_tokens else input_tokens
    else:
        miss_tokens = max(0, int(input_cache_miss_tokens or 0))
    if hit_tokens + miss_tokens < input_tokens:
        miss_tokens += input_tokens - hit_tokens - miss_tokens

    input_cache_hit_price = float(plan["input_cache_hit"])
    input_cache_miss_price = float(plan["input_cache_miss"])
    output_price = float(plan["output"])
    amount = (
        hit_tokens / 1_000_000 * input_cache_hit_price
        + miss_tokens / 1_000_000 * input_cache_miss_price
        + output_tokens / 1_000_000 * output_price
    )
    return {
        "amount": round(amount, 6),
        "currency": str(plan["currency"]),
        "input_cache_hit_tokens": hit_tokens,
        "input_cache_miss_tokens": miss_tokens,
        "input_cache_hit_price_per_million": input_cache_hit_price,
        "input_cache_miss_price_per_million": input_cache_miss_price,
        "output_price_per_million": output_price,
    }


def estimate_cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    result = estimate_cost(provider, model, input_tokens, output_tokens)
    return result["amount"] if result["currency"] == "USD" else 0.0


def price_per_million(provider: str, model: str) -> tuple[float, float]:
    plan = price_plan(provider, model)
    return float(plan["input_cache_miss"]), float(plan["output"])


def price_plan(provider: str, model: str) -> dict[str, float | str]:
    provider_key = provider.lower()
    model_key = model.lower()
    default = _default_plan(provider_key, model_key)
    currency = _currency_env(provider_key, model_key) or str(default["currency"])
    input_override = _price_env(provider_key, model_key, "INPUT")
    hit_override = _price_env(provider_key, model_key, "INPUT_CACHE_HIT")
    miss_override = _price_env(provider_key, model_key, "INPUT_CACHE_MISS")
    output_override = _price_env(provider_key, model_key, "OUTPUT")

    default_input = float(default.get("input", default.get("input_cache_miss", 0.0)))
    default_miss = float(default.get("input_cache_miss", default_input))
    default_hit = float(default.get("input_cache_hit", default_miss))
    return {
        "currency": currency.upper(),
        "input_cache_hit": hit_override if hit_override is not None else default_hit,
        "input_cache_miss": (
            miss_override
            if miss_override is not None
            else input_override
            if input_override is not None
            else default_miss
        ),
        "output": output_override if output_override is not None else float(default.get("output", 0.0)),
    }


def enrich_record_cost(record: dict[str, Any]) -> dict[str, Any]:
    input_tokens = int(record.get("input_tokens") or 0)
    output_tokens = int(record.get("output_tokens") or 0)
    hit_tokens = int(record.get("input_cache_hit_tokens") or record.get("prompt_cache_hit_tokens") or 0)
    miss_value = record.get("input_cache_miss_tokens", record.get("prompt_cache_miss_tokens"))
    miss_tokens = int(miss_value) if miss_value not in (None, "") else None
    result = estimate_cost(
        str(record.get("provider") or ""),
        str(record.get("model") or ""),
        input_tokens,
        output_tokens,
        hit_tokens,
        miss_tokens,
    )
    currency = result["currency"]
    amount = result["amount"]
    record["input_cache_hit_tokens"] = result["input_cache_hit_tokens"]
    record["input_cache_miss_tokens"] = result["input_cache_miss_tokens"]
    record["estimated_cost"] = amount
    record["estimated_cost_currency"] = currency
    record["estimated_cost_usd"] = amount if currency == "USD" else 0.0
    record["estimated_cost_cny"] = amount if currency == "CNY" else 0.0
    record["price_currency"] = currency
    record["input_cache_hit_price_per_million"] = result["input_cache_hit_price_per_million"]
    record["input_cache_miss_price_per_million"] = result["input_cache_miss_price_per_million"]
    record["output_price_per_million"] = result["output_price_per_million"]
    record["input_price_per_million_usd"] = result["input_cache_miss_price_per_million"] if currency == "USD" else 0.0
    record["output_price_per_million_usd"] = result["output_price_per_million"] if currency == "USD" else 0.0
    record["input_price_per_million_cny"] = result["input_cache_miss_price_per_million"] if currency == "CNY" else 0.0
    record["output_price_per_million_cny"] = result["output_price_per_million"] if currency == "CNY" else 0.0
    return record


def load_usage_records(project_dir: Path) -> list[dict[str, Any]]:
    log_path = project_dir / "logs" / "llm_calls.jsonl"
    if not log_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        records.append(enrich_record_cost(item))
    return records


def build_usage_summary(project_dir: Path) -> dict[str, Any]:
    records = load_usage_records(project_dir)
    totals = _empty_totals()
    by_model: dict[tuple[str, str], dict[str, Any]] = {}
    by_workflow: dict[str, dict[str, Any]] = {}
    for record in records:
        _accumulate(totals, record)
        model_key = (str(record.get("provider") or ""), str(record.get("model") or ""))
        by_model.setdefault(model_key, _empty_totals(provider=model_key[0], model=model_key[1]))
        _accumulate(by_model[model_key], record)
        workflow = str(record.get("workflow") or "unknown")
        by_workflow.setdefault(workflow, _empty_totals(workflow=workflow))
        _accumulate(by_workflow[workflow], record)
    return {
        "records": records,
        "totals": totals,
        "by_model": list(by_model.values()),
        "by_workflow": list(by_workflow.values()),
    }


def format_costs(total: dict[str, Any]) -> str:
    cny = float(total.get("estimated_cost_cny") or 0)
    usd = float(total.get("estimated_cost_usd") or 0)
    parts = []
    if cny:
        parts.append(f"¥{cny:.6f}")
    if usd:
        parts.append(f"${usd:.6f}")
    return " / ".join(parts) if parts else "¥0.000000 / $0.000000"


def _empty_totals(**extra: Any) -> dict[str, Any]:
    data = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "input_cache_hit_tokens": 0,
        "input_cache_miss_tokens": 0,
        "estimated_cost": 0.0,
        "estimated_cost_usd": 0.0,
        "estimated_cost_cny": 0.0,
    }
    data.update(extra)
    return data


def _accumulate(total: dict[str, Any], record: dict[str, Any]) -> None:
    total["calls"] += 1
    for key in ["input_tokens", "output_tokens", "total_tokens", "input_cache_hit_tokens", "input_cache_miss_tokens"]:
        total[key] += int(record.get(key) or 0)
    for key in ["estimated_cost_usd", "estimated_cost_cny"]:
        total[key] = round(total[key] + float(record.get(key) or 0), 6)


def _usage_getter(raw_usage: Any):
    if isinstance(raw_usage, dict):
        return lambda key: raw_usage.get(key)
    return lambda key: getattr(raw_usage, key, None)


def _first_int(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _nested_int(raw: Any, key: str) -> int:
    if raw is None:
        return 0
    if isinstance(raw, dict):
        return _first_int(raw.get(key))
    return _first_int(getattr(raw, key, None))


def _default_plan(provider: str, model: str) -> dict[str, float | str]:
    return DEFAULT_PRICE_PER_MILLION.get(
        (provider, model),
        DEFAULT_PRICE_PER_MILLION.get((_provider_family(provider), _model_family(model)), {"currency": "USD", "input": 0.0, "output": 0.0}),
    )


def _price_env(provider: str, model: str, side: str) -> float | None:
    safe_model = _safe_env_part(model)
    safe_provider = _safe_env_part(provider)
    keys = [
        f"NOVEL_COST_{safe_provider}_{safe_model}_{side}_PER_M",
        f"NOVEL_COST_{safe_model}_{side}_PER_M",
    ]
    for key in keys:
        if key not in os.environ:
            continue
        try:
            return float(os.environ[key])
        except ValueError:
            return None
    return None


def _currency_env(provider: str, model: str) -> str | None:
    safe_model = _safe_env_part(model)
    safe_provider = _safe_env_part(provider)
    for key in [f"NOVEL_COST_{safe_provider}_{safe_model}_CURRENCY", f"NOVEL_COST_{safe_model}_CURRENCY"]:
        value = os.environ.get(key, "").strip().upper()
        if value:
            return value
    return None


def _safe_env_part(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.upper()).strip("_")


def _provider_family(provider: str) -> str:
    return "mock" if provider == "mock" else provider


def _model_family(model: str) -> str:
    if model.startswith("anthropic/claude-opus"):
        return "anthropic/claude-opus-4-6"
    if model.startswith("claude-opus"):
        return "claude-opus-4-6"
    if model in {"deepseek-chat", "deepseek-reasoner"}:
        return "deepseek-v4-flash"
    if model.startswith("deepseek-v4-pro"):
        return "deepseek-v4-pro"
    if model.startswith("deepseek-v4-flash"):
        return "deepseek-v4-flash"
    if model.startswith("deepseek"):
        return "deepseek-v4-flash"
    if model.startswith("qwen3"):
        return "qwen3:8b"
    return model
