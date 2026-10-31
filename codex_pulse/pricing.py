"""Official OpenAI API token pricing & multipliers for Codex models (USD per 1M tokens).

Rules verified against OpenAI API pricing:
- Prompt caching: ``cached_input_tokens`` billed at the model's cached rate (5%–25% of input);
  ``cache_write_input_tokens`` billed at ``cache_write`` rate when non-zero.
- Long-context cliff (>272K input tokens on GPT-5.4+ / GPT-6*): when a request's
  ``input_tokens > 272_000``, the ENTIRE request is billed at **2x** input / cached / cache-write
  and **1.5x** output.
- Service tier: Fast / Priority mode (``service_tier`` in ``{"priority", "fast"}``) applies a
  **2x** multiplier across input, cached input, cache write, and output (stacks with long-context).
  Flex / Batch applies **0.5x**.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

LONG_CONTEXT_TOKENS = 272_000
LONG_INPUT_MULT = 2.0
LONG_OUTPUT_MULT = 1.5
FAST_TIER_MULT = 2.0
FLEX_TIER_MULT = 0.5

_DATE_SUFFIX = re.compile(r'-\d{4}-\d{2}-\d{2}$')
_SEP_RUN = re.compile(r'[\s_]+')


@dataclass(frozen=True)
class ModelRate:
    inp: float
    cached: float
    out: float
    cache_write: float | None = None
    long_context_threshold: int | None = LONG_CONTEXT_TOKENS

    @property
    def cwrite(self) -> float:
        return self.inp * 1.25 if self.cache_write is None else self.cache_write


# Standard short-context (<=272K input) API rates in USD per 1M tokens:
# ModelRate(input, cached_input, output, cache_write, long_context_threshold)
MODEL_RATES: dict[str, ModelRate] = {
    # --- Codex Desktop current model picker (GPT-6.1 & GPT-6 series) ---
    'gpt-6.1-sol': ModelRate(2.00, 0.10, 10.00, 2.50),
    'gpt-6-astra': ModelRate(10.00, 1.00, 50.00, 12.50),
    'gpt-6.1-astra': ModelRate(10.00, 1.00, 50.00, 12.50),
    'gpt-6.1-terra': ModelRate(1.00, 0.05, 5.00, 1.25),
    'gpt-6-terra': ModelRate(1.00, 0.05, 5.00, 1.25),
    'gpt-6-sol': ModelRate(2.00, 0.20, 10.00, 2.50),
    'gpt-6-luna': ModelRate(0.10, 0.01, 0.50, 0.125),
    'gpt-6.1-luna': ModelRate(0.10, 0.01, 0.50, 0.125),

    # --- Codex Desktop GPT-5.6 series & internal routing aliases ---
    'gpt-5.6-sol': ModelRate(4.00, 0.40, 20.00, 5.00),
    'gpt-5.6-terra': ModelRate(2.00, 0.20, 12.00, 2.50),
    'gpt-5.6-luna': ModelRate(0.20, 0.02, 1.20, 0.25),
    'gpt-reserve': ModelRate(0.20, 0.02, 1.20, 0.25),        # Luna Reserve -> gpt-5.6-luna
    'codex-auto-review': ModelRate(0.20, 0.02, 1.20, 0.25),  # Guardian auto-review model

    # --- GPT-5.0 – 5.5 & Codex variants ---
    'gpt-5.5': ModelRate(5.00, 0.50, 30.00, 6.25),
    'gpt-5.4': ModelRate(2.50, 0.25, 15.00, 3.125),
    'gpt-5.4-mini': ModelRate(0.75, 0.075, 4.50, 0.9375),
    'gpt-5.4-nano': ModelRate(0.20, 0.02, 1.25, 0.25),
    'gpt-5.3-codex': ModelRate(1.75, 0.175, 14.00, 2.1875, None),
    'gpt-5.3-codex-spark': ModelRate(1.75, 0.175, 14.00, 2.1875, None),
    'gpt-5.3': ModelRate(1.75, 0.175, 14.00, 2.1875, None),
    'gpt-5.2-codex': ModelRate(1.75, 0.175, 14.00, 2.1875, None),
    'gpt-5.2': ModelRate(1.75, 0.175, 14.00, 2.1875, None),
    'gpt-5.1-codex-max': ModelRate(1.25, 0.125, 10.00, 1.5625, None),
    'gpt-5.1-codex-mini': ModelRate(0.25, 0.025, 2.00, 0.3125, None),
    'gpt-5.1-codex': ModelRate(1.25, 0.125, 10.00, 1.5625, None),
    'gpt-5.1': ModelRate(1.25, 0.125, 10.00, 1.5625, None),
    'gpt-5-codex': ModelRate(1.25, 0.125, 10.00, 1.5625, None),
    'gpt-5': ModelRate(1.25, 0.125, 10.00, 1.5625, None),
    'gpt-5-mini': ModelRate(0.25, 0.025, 2.00, 0.3125, None),
    'codex-mini-latest': ModelRate(1.50, 0.375, 6.00, 1.50, None),
    'gpt-5-nano': ModelRate(0.05, 0.005, 0.40, 0.0625, None),

    # --- Reasoning & GPT-4.1 legacy (flat context pricing) ---
    'o3': ModelRate(2.00, 0.50, 8.00, 2.00, None),
    'o4-mini': ModelRate(1.10, 0.275, 4.40, 1.10, None),
    'gpt-4.1': ModelRate(2.00, 0.50, 8.00, 2.00, None),
    'gpt-4.1-mini': ModelRate(0.40, 0.10, 1.60, 0.40, None),
    'gpt-4.1-nano': ModelRate(0.10, 0.025, 0.40, 0.10, None),
}

_FAMILY_FALLBACKS: tuple[tuple[str, ModelRate], ...] = (
    ('astra', MODEL_RATES['gpt-6-astra']),
    ('5.6-sol', MODEL_RATES['gpt-5.6-sol']),
    ('5.6-terra', MODEL_RATES['gpt-5.6-terra']),
    ('5.6-luna', MODEL_RATES['gpt-5.6-luna']),
    ('6-sol', MODEL_RATES['gpt-6-sol']),
    ('-sol', MODEL_RATES['gpt-6.1-sol']),
    ('-terra', MODEL_RATES['gpt-6.1-terra']),
    ('-luna', MODEL_RATES['gpt-6-luna']),
    ('gpt-5.5', MODEL_RATES['gpt-5.5']),
    ('gpt-5.4-mini', MODEL_RATES['gpt-5.4-mini']),
    ('gpt-5.4-nano', MODEL_RATES['gpt-5.4-nano']),
    ('gpt-5.4', MODEL_RATES['gpt-5.4']),
    ('gpt-5.3', MODEL_RATES['gpt-5.3-codex']),
    ('gpt-5.2', MODEL_RATES['gpt-5.2-codex']),
    ('gpt-5.1-codex-mini', MODEL_RATES['gpt-5.1-codex-mini']),
    ('gpt-5.1', MODEL_RATES['gpt-5.1-codex']),
    ('gpt-5-mini', MODEL_RATES['gpt-5-mini']),
    ('gpt-5-nano', MODEL_RATES['gpt-5-nano']),
    ('gpt-5', MODEL_RATES['gpt-5']),
)


def normalize_model(model: str | None) -> str:
    if not model:
        return ''
    s = model.strip().lower().split('/')[-1]
    return _SEP_RUN.sub('-', s)


def _parse_override(entry) -> ModelRate | None:
    try:
        if isinstance(entry, (list, tuple)) and len(entry) >= 3:
            cw = float(entry[3]) if len(entry) >= 4 else None
            return ModelRate(float(entry[0]), float(entry[1]), float(entry[2]), cw)
        if isinstance(entry, dict):
            cw = entry.get('cache_write')
            return ModelRate(float(entry['input']), float(entry['cached']), float(entry['output']),
                             float(cw) if cw is not None else None)
    except (KeyError, TypeError, ValueError):
        return None
    return None


def resolve_rate(model: str | None, overrides: dict | None = None) -> ModelRate | None:
    key = normalize_model(model)
    if not key:
        return None
    base = _DATE_SUFFIX.sub('', key)
    if isinstance(overrides, dict):
        norm_overrides = {normalize_model(k): v for k, v in overrides.items()}
        for candidate in (key, base):
            if candidate in norm_overrides:
                parsed = _parse_override(norm_overrides[candidate])
                if parsed is not None:
                    return parsed
    if key in MODEL_RATES:
        return MODEL_RATES[key]
    if base in MODEL_RATES:
        return MODEL_RATES[base]
    for token, rate in _FAMILY_FALLBACKS:
        if token in base:
            return rate
    return None


def is_fast_tier(service_tier: str | None) -> bool:
    return bool(service_tier) and service_tier.strip().lower() in ('priority', 'fast')


def tier_multiplier(service_tier: str | None) -> float:
    if not service_tier:
        return 1.0
    t = service_tier.strip().lower()
    if t in ('priority', 'fast'):
        return FAST_TIER_MULT
    if t in ('flex', 'batch'):
        return FLEX_TIER_MULT
    return 1.0


def is_long_context(input_tokens: int | None, rate: ModelRate | None) -> bool:
    return bool(
        rate is not None
        and rate.long_context_threshold is not None
        and input_tokens is not None
        and input_tokens > rate.long_context_threshold
    )


def cost_for_usage(usage, model: str | None, service_tier: str | None = None, *,
                   check_long_context: bool = True, overrides: dict | None = None) -> tuple[float, float] | None:
    """Return ``(actual_cost_usd, cache_saved_usd)`` for a :class:`Usage`, or ``None`` if model unknown."""
    if usage is None:
        return None
    rate = resolve_rate(model, overrides)
    if rate is None:
        return None
    inp = max(0, int(usage.input_tokens))
    cached = min(inp, max(0, int(usage.cached_input_tokens)))
    cwrite = min(max(0, inp - cached), max(0, int(getattr(usage, 'cache_write_input_tokens', 0))))
    uncached = max(0, inp - cached - cwrite)
    out = max(0, int(usage.output_tokens))

    long_ctx = check_long_context and is_long_context(inp, rate)
    in_mult = LONG_INPUT_MULT if long_ctx else 1.0
    out_mult = LONG_OUTPUT_MULT if long_ctx else 1.0
    tier_mult = tier_multiplier(service_tier)

    p_in = rate.inp * in_mult * tier_mult
    p_cached = rate.cached * in_mult * tier_mult
    p_cwrite = rate.cwrite * in_mult * tier_mult
    p_out = rate.out * out_mult * tier_mult

    actual = (uncached * p_in + cached * p_cached + cwrite * p_cwrite + out * p_out) / 1_000_000
    baseline = (inp * p_in + out * p_out) / 1_000_000
    return actual, max(0.0, baseline - actual)


def fmt_usd(amount: float | None, *, compact: bool = False) -> str:
    if amount is None:
        return '—'
    v = max(0.0, float(amount))
    if v == 0.0:
        return '$0.00'
    if v < 0.01:
        return '<$0.01' if compact else (f'${v:.4f}' if v < 0.001 else f'${v:.3f}')
    if v < 100.0:
        return f'${v:.2f}'
    if v < 1000.0:
        return f'${v:.1f}' if compact else f'${v:,.2f}'
    if compact:
        k = v / 1000.0
        return f'${k:.2f}K' if k < 10 else f'${k:.1f}K'
    return f'${v:,.2f}'


def _trim_price(p: float) -> str:
    rounded = round(p, 4)
    if rounded >= 1 and rounded == int(rounded):
        return f'${int(rounded)}'
    s = f'{rounded:.4f}'.rstrip('0').rstrip('.')
    return f'${s}'


def fmt_rate(model: str | None, service_tier: str | None = None,
             last_input_tokens: int | None = None, overrides: dict | None = None) -> str:
    rate = resolve_rate(model, overrides)
    if rate is None:
        return '—'
    long_ctx = is_long_context(last_input_tokens, rate)
    in_mult = LONG_INPUT_MULT if long_ctx else 1.0
    out_mult = LONG_OUTPUT_MULT if long_ctx else 1.0
    t_mult = tier_multiplier(service_tier)
    base = (f'{_trim_price(rate.inp * in_mult * t_mult)} / '
            f'{_trim_price(rate.cached * in_mult * t_mult)} / '
            f'{_trim_price(rate.out * out_mult * t_mult)} · 1M')
    tags = []
    if t_mult > 1.0:
        tags.append('Fast 2×')
    elif t_mult < 1.0:
        tags.append('Flex 0.5×')
    if long_ctx:
        tags.append('>272K')
    return f"{base} ({' · '.join(tags)})" if tags else base
