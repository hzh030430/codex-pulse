"""Incremental metrics over one Codex rollout file (``rollout-*.jsonl``).

Feed lines in file order with :meth:`SessionMetrics.feed`, then read an
immutable :class:`Snapshot`.

Data sources inside a rollout, newest Codex first:

``token_usage_record``     written when a model response completes; per-response
                           ``usage``, ``turn_token_usage``, ``thread_token_usage``.
``event_msg/token_count``  ``info.last_token_usage`` / ``info.total_token_usage`` /
                           ``info.model_context_window`` and ``rate_limits``.
``event_msg/task_started`` / ``task_complete``  turn boundaries, TTFT, duration.
``turn_context``           model, reasoning effort, approval / sandbox policy.
``compacted``              context compaction.

TPS = output tokens / request wall time. Wall time runs from the last input
boundary (user message, tool output, turn start, previous response) to the
response completing, so it includes time-to-first-token: a conservative,
end-to-end throughput, not pure decode speed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from .pricing import cost_for_usage, is_fast_tier, is_long_context, resolve_rate

_HEAD = re.compile(
    r'"timestamp":"(?P<ts>[^"]+)".*?"type":"(?P<type>[a-z_]+)"'
    r'(?:,"payload":\{"type":"(?P<ptype>[a-zA-Z_]+)")?'
)
_ROLE = re.compile(r'"role":"(?P<role>[a-z_]+)"')

_OUTPUT_ITEMS = {
    'reasoning', 'function_call', 'custom_tool_call', 'local_shell_call',
    'web_search_call', 'image_generation_call', 'tool_search_call',
}
_TOOL_CALLS = {'function_call', 'custom_tool_call', 'local_shell_call', 'web_search_call', 'tool_search_call'}
_INPUT_ITEMS = {
    'function_call_output', 'custom_tool_call_output', 'local_shell_call_output',
    'tool_search_output', 'mcp_tool_call_output',
}
_INPUT_EVENTS = {'task_started', 'user_message', 'turn_aborted', 'task_complete'}

MIN_SAMPLE_SECONDS = 0.3
MAX_PLAUSIBLE_TPS = 3000.0
WEEK_MINUTES = 7 * 24 * 60


def parse_ts(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, AttributeError):
        return None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    cache_write_input_tokens: int = 0

    @classmethod
    def from_dict(cls, d) -> 'Usage | None':
        if not isinstance(d, dict):
            return None
        def num(key):
            v = d.get(key)
            return int(v) if isinstance(v, (int, float)) else 0
        return cls(num('input_tokens'), num('cached_input_tokens'), num('output_tokens'),
                   num('reasoning_output_tokens'), num('total_tokens'), num('cache_write_input_tokens'))

    @property
    def cache_rate(self) -> float | None:
        if self.input_tokens <= 0:
            return None
        return min(1.0, self.cached_input_tokens / self.input_tokens)

    @property
    def reasoning_share(self) -> float | None:
        if self.output_tokens <= 0:
            return None
        return min(1.0, self.reasoning_output_tokens / self.output_tokens)


@dataclass(frozen=True)
class RateWindow:
    used_percent: float
    window_minutes: int | None
    resets_at: float | None

    @property
    def is_weekly(self) -> bool:
        return self.window_minutes is not None and self.window_minutes >= WEEK_MINUTES - 60

    @classmethod
    def from_dict(cls, d) -> 'RateWindow | None':
        if not isinstance(d, dict) or not isinstance(d.get('used_percent'), (int, float)):
            return None
        wm, ra = d.get('window_minutes'), d.get('resets_at')
        return cls(float(d['used_percent']), int(wm) if isinstance(wm, (int, float)) else None,
                   float(ra) if isinstance(ra, (int, float)) else None)


@dataclass(frozen=True)
class Snapshot:
    path: str | None = None
    session_id: str | None = None
    started_at: float | None = None
    model: str | None = None
    effort: str | None = None
    approval: str | None = None
    sandbox: str | None = None
    cwd: str | None = None
    # tokens
    totals: Usage | None = None
    turn_usage: Usage | None = None
    # context
    context_used: int | None = None
    context_window: int | None = None
    compactions: int = 0
    last_compaction_at: float | None = None
    # speed
    session_tps: float | None = None
    last_tps: float | None = None
    last_output_tokens: int | None = None
    last_seconds: float | None = None
    samples: int = 0
    avg_ttft_ms: float | None = None
    avg_turn_ms: float | None = None
    # turns
    turns: int = 0
    active: bool = False
    turn_started_at: float | None = None
    turn_tool_calls: int = 0
    # quota
    weekly: RateWindow | None = None
    short: RateWindow | None = None
    credits: str | None = None
    plan: str | None = None
    # cost (API-equivalent USD)
    service_tier: str | None = None
    last_input_tokens: int | None = None
    cost_usd: float | None = None
    cache_saved_usd: float | None = None
    turn_cost_usd: float | None = None
    fast_requests: int = 0
    long_context_requests: int = 0
    subagent_cost_usd: float = 0.0
    subagent_saved_usd: float = 0.0
    subagent_count: int = 0
    updated_at: float | None = None
    error: str | None = None

    @property
    def context_ratio(self) -> float | None:
        if not self.context_used or not self.context_window:
            return None
        return min(1.0, self.context_used / self.context_window)

    @property
    def main_cost_usd(self) -> float | None:
        if self.cost_usd is not None:
            return self.cost_usd
        res = cost_for_usage(self.totals, self.model, self.service_tier, check_long_context=False)
        return res[0] if res is not None else None

    @property
    def main_saved_usd(self) -> float | None:
        if self.cache_saved_usd is not None:
            return self.cache_saved_usd
        res = cost_for_usage(self.totals, self.model, self.service_tier, check_long_context=False)
        return res[1] if res is not None else None

    @property
    def total_cost_usd(self) -> float | None:
        mc = self.main_cost_usd
        if mc is None and not self.subagent_count:
            return None
        return (mc or 0.0) + self.subagent_cost_usd

    @property
    def total_saved_usd(self) -> float | None:
        ms = self.main_saved_usd
        if ms is None and not self.subagent_count:
            return None
        return (ms or 0.0) + self.subagent_saved_usd

    @property
    def effective_turn_cost_usd(self) -> float | None:
        if self.turn_cost_usd is not None:
            return self.turn_cost_usd
        res = cost_for_usage(self.turn_usage, self.model, self.service_tier, check_long_context=False)
        return res[0] if res is not None else None


@dataclass
class SessionMetrics:
    path: str | None = None
    session_id: str | None = None
    started_at: float | None = None
    model: str | None = None
    effort: str | None = None
    approval: str | None = None
    sandbox: str | None = None
    cwd: str | None = None
    totals: Usage | None = None
    turn_usage: Usage | None = None
    context_used: int | None = None
    context_window: int | None = None
    compactions: int = 0
    last_compaction_at: float | None = None
    has_records: bool = False
    boundary_ts: float | None = None
    pending_start: float | None = None
    last_output_ts: float | None = None
    last_count_total: int | None = None
    out_sum: int = 0
    sec_sum: float = 0.0
    samples: int = 0
    last_tps: float | None = None
    last_output_tokens: int | None = None
    last_seconds: float | None = None
    ttft_sum: float = 0.0
    ttft_n: int = 0
    turn_ms_sum: float = 0.0
    turn_ms_n: int = 0
    turns: int = 0
    active: bool = False
    turn_started_at: float | None = None
    turn_tool_calls: int = 0
    weekly: RateWindow | None = None
    short: RateWindow | None = None
    credits: str | None = None
    plan: str | None = None
    service_tier: str | None = None
    last_input_tokens: int | None = None
    price_overrides: dict | None = None
    cost_sum: float = 0.0
    saved_sum: float = 0.0
    turn_cost_sum: float = 0.0
    turn_cost_n: int = 0
    priced_n: int = 0
    fast_requests: int = 0
    long_context_requests: int = 0
    priced_in: int = 0
    priced_cached: int = 0
    priced_cwrite: int = 0
    priced_out: int = 0
    updated_at: float | None = None
    seen_record_ids: set = field(default_factory=set)

    # ------------------------------------------------------------------ feed
    def feed(self, line: str) -> None:
        head = _HEAD.search(line, 0, 400)
        if not head:
            return
        kind, ptype = head.group('type'), head.group('ptype')
        ts = parse_ts(head.group('ts'))
        if ts is None:
            return

        if kind == 'token_usage_record':
            self._record(ts, line)
        elif kind == 'response_item':
            if ptype in _INPUT_ITEMS:
                self.boundary_ts = ts
            elif ptype == 'message':
                role = _ROLE.search(line, 0, 600)
                if role and role.group('role') == 'assistant':
                    self._output(ts)
                else:
                    self.boundary_ts = ts
            elif ptype in _OUTPUT_ITEMS:
                self._output(ts)
                if ptype in _TOOL_CALLS and self.active:
                    self.turn_tool_calls += 1
        elif kind == 'event_msg':
            if ptype == 'token_count':
                self._token_count(ts, line)
            elif ptype == 'thread_settings_applied':
                self._thread_settings(line)
            elif ptype in _INPUT_EVENTS:
                self.boundary_ts = ts
                if ptype == 'task_started':
                    self._task_started(ts, line)
                elif ptype == 'task_complete':
                    self._task_complete(line)
                elif ptype == 'turn_aborted':
                    self.active = False
        elif kind == 'turn_context':
            self.boundary_ts = ts
            self._turn_context(line)
        elif kind == 'compacted':
            self.boundary_ts = ts
            self.compactions += 1
            self.last_compaction_at = ts
        elif kind == 'session_meta':
            self._session_meta(ts, line)

    # ------------------------------------------------------------- handlers
    @staticmethod
    def _payload(line: str) -> dict:
        try:
            p = json.loads(line).get('payload')
        except ValueError:
            return {}
        return p if isinstance(p, dict) else {}

    def _session_meta(self, ts: float, line: str) -> None:
        p = self._payload(line)
        self.session_id = p.get('id') or p.get('session_id') or self.session_id
        self.started_at = parse_ts(p.get('timestamp') or '') or ts
        self.cwd = p.get('cwd') or self.cwd
        if p.get('service_tier') is not None:
            self.service_tier = p['service_tier'] or 'default'

    def _thread_settings(self, line: str) -> None:
        ts = self._payload(line).get('thread_settings')
        if isinstance(ts, dict):
            self.model = ts.get('model') or self.model
            self.effort = ts.get('reasoning_effort') or self.effort
            if 'service_tier' in ts:
                self.service_tier = ts['service_tier'] or 'default'

    def _turn_context(self, line: str) -> None:
        p = self._payload(line)
        settings = ((p.get('collaboration_mode') or {}).get('settings') or {})
        self.model = p.get('model') or settings.get('model') or self.model
        if 'service_tier' in p:
            self.service_tier = p['service_tier'] or 'default'
        elif 'service_tier' in settings:
            self.service_tier = settings['service_tier'] or 'default'
        self.effort = p.get('effort') or settings.get('reasoning_effort') or self.effort
        self.approval = p.get('approval_policy') or self.approval
        sandbox = p.get('sandbox_policy')
        if isinstance(sandbox, dict):
            self.sandbox = sandbox.get('type') or self.sandbox
        elif isinstance(sandbox, str):
            self.sandbox = sandbox
        self.cwd = p.get('cwd') or self.cwd

    def _task_started(self, ts: float, line: str) -> None:
        p = self._payload(line)
        self.turns += 1
        self.active = True
        self.turn_started_at = ts
        self.turn_tool_calls = 0
        self.turn_usage = None
        self.turn_cost_sum = 0.0
        self.turn_cost_n = 0
        if isinstance(p.get('model_context_window'), (int, float)):
            self.context_window = int(p['model_context_window'])

    def _price_request(self, usage: Usage, tier_override: str | None = None) -> None:
        tier = tier_override or self.service_tier
        self.last_input_tokens = usage.input_tokens
        res = cost_for_usage(usage, self.model, tier, check_long_context=True,
                             overrides=self.price_overrides)
        if res is None:
            return
        cost, saved = res
        rate = resolve_rate(self.model, self.price_overrides)
        if is_fast_tier(tier):
            self.fast_requests += 1
        if is_long_context(usage.input_tokens, rate):
            self.long_context_requests += 1
        self.cost_sum += cost
        self.saved_sum += saved
        self.turn_cost_sum += cost
        self.turn_cost_n += 1
        self.priced_n += 1
        self.priced_in += usage.input_tokens
        self.priced_cached += usage.cached_input_tokens
        self.priced_cwrite += usage.cache_write_input_tokens
        self.priced_out += usage.output_tokens

    def _task_complete(self, line: str) -> None:
        p = self._payload(line)
        self.active = False
        ttft, dur = p.get('time_to_first_token_ms'), p.get('duration_ms')
        if isinstance(ttft, (int, float)) and ttft > 0:
            self.ttft_sum += ttft
            self.ttft_n += 1
        if isinstance(dur, (int, float)) and dur > 0:
            self.turn_ms_sum += dur
            self.turn_ms_n += 1

    def _output(self, ts: float) -> None:
        if self.pending_start is None:
            self.pending_start = self.boundary_ts
        self.last_output_ts = ts

    def _sample(self, output_tokens: int, seconds: float | None) -> None:
        if seconds is None or output_tokens <= 0 or seconds < MIN_SAMPLE_SECONDS:
            return
        tps = output_tokens / seconds
        if tps > MAX_PLAUSIBLE_TPS:
            return
        self.out_sum += output_tokens
        self.sec_sum += seconds
        self.samples += 1
        self.last_tps, self.last_output_tokens, self.last_seconds = tps, output_tokens, seconds

    def _record(self, ts: float, line: str) -> None:
        payload = self._payload(line)
        rid = payload.get('response_id')
        if rid:
            if rid in self.seen_record_ids:
                return
            self.seen_record_ids.add(rid)
        self.has_records = True
        usage = Usage.from_dict(payload.get('usage'))
        thread = Usage.from_dict(payload.get('thread_token_usage'))
        turn = Usage.from_dict(payload.get('turn_token_usage'))
        if thread is not None:
            self.totals = thread
        if turn is not None:
            self.turn_usage = turn
        if usage is not None:
            self.context_used = usage.input_tokens + usage.output_tokens
            seconds = ts - self.boundary_ts if self.boundary_ts is not None else None
            self._sample(usage.output_tokens, seconds)
            rec_tier = payload.get('service_tier') if isinstance(payload.get('service_tier'), str) else None
            self._price_request(usage, rec_tier)
        self.boundary_ts = ts
        self.pending_start = self.last_output_ts = None
        self.updated_at = ts

    def _token_count(self, ts: float, line: str) -> None:
        payload = self._payload(line)
        rl = payload.get('rate_limits')
        if isinstance(rl, dict):
            for key in ('primary', 'secondary'):
                win = RateWindow.from_dict(rl.get(key))
                if win is None:
                    continue
                if win.is_weekly:
                    self.weekly = win
                else:
                    self.short = win
            credits = rl.get('credits')
            if isinstance(credits, dict) and credits.get('balance') is not None:
                self.credits = 'unlimited' if credits.get('unlimited') else str(credits.get('balance'))
            self.plan = rl.get('plan_type') or self.plan
        info = payload.get('info')
        if not isinstance(info, dict):
            return
        if isinstance(info.get('model_context_window'), (int, float)):
            self.context_window = int(info['model_context_window'])
        total = Usage.from_dict(info.get('total_token_usage'))
        last = Usage.from_dict(info.get('last_token_usage'))
        if total is None:
            return
        if self.last_count_total == total.total_tokens:
            return
        self.last_count_total = total.total_tokens
        if not self.has_records:
            self.totals = total
            if last is not None:
                self.context_used = last.input_tokens + last.output_tokens
                if self.pending_start is not None and self.last_output_ts is not None:
                    self._sample(last.output_tokens, self.last_output_ts - self.pending_start)
                self._price_request(last)
            self.pending_start = self.last_output_ts = None
            self.updated_at = ts
        elif self.totals is None or total.total_tokens > self.totals.total_tokens:
            self.totals = total

    # ------------------------------------------------------------- snapshot
    def snapshot(self) -> Snapshot:
        cost_usd = self.cost_sum if self.priced_n else None
        saved_usd = self.saved_sum if self.priced_n else None
        if self.totals is not None and self.model:
            rem_in = max(0, self.totals.input_tokens - self.priced_in)
            rem_out = max(0, self.totals.output_tokens - self.priced_out)
            if rem_in > 0 or rem_out > 0:
                rem = Usage(
                    rem_in,
                    min(rem_in, max(0, self.totals.cached_input_tokens - self.priced_cached)),
                    rem_out, 0, rem_in + rem_out,
                    min(rem_in, max(0, self.totals.cache_write_input_tokens - self.priced_cwrite)),
                )
                extra = cost_for_usage(rem, self.model, self.service_tier, check_long_context=False,
                                       overrides=self.price_overrides)
                if extra is not None:
                    cost_usd = (cost_usd or 0.0) + extra[0]
                    saved_usd = (saved_usd or 0.0) + extra[1]
        turn_cost = self.turn_cost_sum if self.turn_cost_n else None
        return Snapshot(
            path=self.path, session_id=self.session_id, started_at=self.started_at,
            model=self.model, effort=self.effort, approval=self.approval, sandbox=self.sandbox, cwd=self.cwd,
            totals=self.totals, turn_usage=self.turn_usage,
            context_used=self.context_used, context_window=self.context_window,
            compactions=self.compactions, last_compaction_at=self.last_compaction_at,
            session_tps=(self.out_sum / self.sec_sum) if self.sec_sum > 0 else None,
            last_tps=self.last_tps, last_output_tokens=self.last_output_tokens,
            last_seconds=self.last_seconds, samples=self.samples,
            avg_ttft_ms=(self.ttft_sum / self.ttft_n) if self.ttft_n else None,
            avg_turn_ms=(self.turn_ms_sum / self.turn_ms_n) if self.turn_ms_n else None,
            turns=self.turns, active=self.active, turn_started_at=self.turn_started_at,
            turn_tool_calls=self.turn_tool_calls,
            weekly=self.weekly, short=self.short, credits=self.credits, plan=self.plan,
            service_tier=self.service_tier, last_input_tokens=self.last_input_tokens,
            cost_usd=cost_usd, cache_saved_usd=saved_usd, turn_cost_usd=turn_cost,
            fast_requests=self.fast_requests, long_context_requests=self.long_context_requests,
            updated_at=self.updated_at,
        )


def human(n: float | int | None) -> str:
    if n is None:
        return '—'
    n = float(n)
    for unit, size in (('B', 1e9), ('M', 1e6), ('K', 1e3)):
        if abs(n) >= size:
            v = n / size
            return f'{v:.1f}{unit}' if v < 100 else f'{v:.0f}{unit}'
    return f'{n:.0f}'


def duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return '—'
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f'{d}天{h}小时'
    if h:
        return f'{h}小时{m}分'
    if m:
        return f'{m}分{s}秒'
    return f'{s}秒'
