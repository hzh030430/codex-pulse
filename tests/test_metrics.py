import json
import unittest

from codex_pulse.metrics import SessionMetrics, Usage, human
from codex_pulse.overlay import SIZE_MAX, SIZE_MIN, parse_opacity, parse_size
from codex_pulse.pricing import cost_for_usage, fmt_rate, fmt_usd, resolve_rate
from codex_pulse.threads import clean_title


def line(ts, kind, payload=None):
    obj = {'timestamp': ts, 'ordinal': 0, 'type': kind}
    if payload is not None:
        obj['payload'] = payload
    return json.dumps(obj, separators=(',', ':'))


def usage(inp, cached, out, reasoning=0):
    return {'input_tokens': inp, 'cached_input_tokens': cached, 'cache_write_input_tokens': 0,
            'output_tokens': out, 'reasoning_output_tokens': reasoning, 'total_tokens': inp + out}


class RecordFormat(unittest.TestCase):
    def test_tokens_cache_and_tps_from_usage_records(self):
        m = SessionMetrics()
        feed = [
            line('2026-10-31T00:00:00.000Z', 'session_meta', {'id': '01a189bf-14b2-73a2-9e3e-0561b1e3afff'}),
            line('2026-10-31T00:00:01.000Z', 'event_msg', {'type': 'task_started'}),
            line('2026-10-31T00:00:01.100Z', 'turn_context', {'model': 'gpt-x'}),
            line('2026-10-31T00:00:03.000Z', 'response_item', {'type': 'reasoning'}),
            line('2026-10-31T00:00:05.100Z', 'response_item', {'type': 'custom_tool_call'}),
            # first response: 400 output tokens in 4.0 s (from turn_context boundary)
            line('2026-10-31T00:00:05.100Z', 'token_usage_record',
                 {'response_id': 'r1', 'usage': usage(1000, 0, 400), 'thread_token_usage': usage(1000, 0, 400)}),
            line('2026-10-31T00:00:09.000Z', 'response_item', {'type': 'custom_tool_call_output'}),
            line('2026-10-31T00:00:09.020Z', 'event_msg', {'type': 'token_count', 'info': {
                'total_token_usage': usage(1000, 0, 400), 'last_token_usage': usage(1000, 0, 400)}}),
            line('2026-10-31T00:00:10.000Z', 'response_item', {'type': 'message', 'role': 'assistant'}),
            # second response: 100 output tokens in 1.0 s (from tool output boundary)
            line('2026-10-31T00:00:10.000Z', 'token_usage_record',
                 {'response_id': 'r2', 'usage': usage(1200, 900, 100), 'thread_token_usage': usage(2200, 900, 500)}),
            line('2026-10-31T00:00:10.500Z', 'event_msg', {'type': 'task_complete'}),
        ]
        for raw in feed:
            m.feed(raw)
        s = m.snapshot()
        self.assertEqual(s.session_id, '01a189bf-14b2-73a2-9e3e-0561b1e3afff')
        self.assertEqual(s.model, 'gpt-x')
        self.assertEqual(s.totals.total_tokens, 2700)
        self.assertAlmostEqual(s.totals.cache_rate, 900 / 2200)
        self.assertAlmostEqual(s.session_tps, 500 / 5.0)
        self.assertAlmostEqual(s.last_tps, 100.0)
        self.assertEqual(s.samples, 2)
        self.assertFalse(s.active)

    def test_duplicate_record_is_ignored(self):
        m = SessionMetrics()
        rec = line('2026-10-31T00:00:02.000Z', 'token_usage_record',
                   {'response_id': 'r1', 'usage': usage(10, 5, 50), 'thread_token_usage': usage(10, 5, 50)})
        m.feed(line('2026-10-31T00:00:00.000Z', 'event_msg', {'type': 'user_message'}))
        m.feed(rec)
        m.feed(rec)
        self.assertEqual(m.snapshot().samples, 1)


class LegacyFormat(unittest.TestCase):
    def test_token_count_only(self):
        m = SessionMetrics()
        for raw in [
            line('2026-10-31T00:00:00.000Z', 'event_msg', {'type': 'user_message'}),
            line('2026-10-31T00:00:01.000Z', 'response_item', {'type': 'reasoning'}),
            line('2026-10-31T00:00:03.000Z', 'response_item', {'type': 'message', 'role': 'assistant'}),
            line('2026-10-31T00:00:03.010Z', 'event_msg', {'type': 'token_count', 'info': {
                'total_token_usage': usage(500, 250, 300), 'last_token_usage': usage(500, 250, 300)}}),
            line('2026-10-31T00:00:03.020Z', 'event_msg', {'type': 'token_count', 'info': None}),
        ]:
            m.feed(raw)
        s = m.snapshot()
        self.assertEqual(s.totals.total_tokens, 800)
        self.assertAlmostEqual(s.totals.cache_rate, 0.5)
        self.assertAlmostEqual(s.session_tps, 100.0)


class Format(unittest.TestCase):
    def test_human(self):
        self.assertEqual(human(None), '—')
        self.assertEqual(human(950), '950')
        self.assertEqual(human(12_345), '12.3K')
        self.assertEqual(human(747_409_756), '747M')
        self.assertEqual(human(1_234_567_890), '1.2B')

    def test_clean_title(self):
        self.assertEqual(clean_title('**重构异步任务池**\n第二行'), '重构异步任务池')
        self.assertEqual(clean_title(None), '(未命名会话)')
        self.assertTrue(clean_title('x' * 200).endswith('…'))


class ContextQuotaTurns(unittest.TestCase):
    def test_context_quota_and_turn_stats(self):
        m = SessionMetrics()
        rl = {'limit_id': 'codex', 'primary': {'used_percent': 11.0, 'window_minutes': 10080, 'resets_at': 1793905272},
              'secondary': {'used_percent': 40.0, 'window_minutes': 300, 'resets_at': 1793400000},
              'credits': {'has_credits': True, 'unlimited': False, 'balance': '1250.50'}, 'plan_type': 'pro'}
        for raw in [
            line('2026-10-31T00:00:00.000Z', 'event_msg', {'type': 'task_started', 'model_context_window': 475000}),
            line('2026-10-31T00:00:00.100Z', 'turn_context', {
                'model': 'gpt-x', 'approval_policy': 'on-request', 'sandbox_policy': {'type': 'read-only'},
                'collaboration_mode': {'settings': {'reasoning_effort': 'medium'}}}),
            line('2026-10-31T00:00:01.000Z', 'response_item', {'type': 'custom_tool_call'}),
            line('2026-10-31T00:00:02.000Z', 'token_usage_record', {
                'response_id': 'r1', 'usage': usage(280000, 270000, 2000),
                'turn_token_usage': usage(280000, 270000, 2000), 'thread_token_usage': usage(900000, 850000, 9000)}),
            line('2026-10-31T00:00:03.000Z', 'response_item', {'type': 'custom_tool_call_output'}),
            line('2026-10-31T00:00:03.010Z', 'event_msg', {'type': 'token_count', 'info': {
                'total_token_usage': usage(900000, 850000, 9000), 'last_token_usage': usage(280000, 270000, 2000),
                'model_context_window': 475000}, 'rate_limits': rl}),
            line('2026-10-31T00:00:04.000Z', 'compacted', {'message': ''}),
            line('2026-10-31T00:00:05.000Z', 'event_msg', {
                'type': 'task_complete', 'duration_ms': 5000, 'time_to_first_token_ms': 1200}),
        ]:
            m.feed(raw)
        s = m.snapshot()
        self.assertEqual((s.model, s.effort, s.approval, s.sandbox), ('gpt-x', 'medium', 'on-request', 'read-only'))
        self.assertEqual(s.context_used, 282000)
        self.assertEqual(s.context_window, 475000)
        self.assertAlmostEqual(s.context_ratio, 282000 / 475000)
        self.assertEqual(s.compactions, 1)
        self.assertEqual(s.weekly.used_percent, 11.0)
        self.assertEqual(s.short.used_percent, 40.0)
        self.assertEqual((s.credits, s.plan), ('1250.50', 'pro'))
        self.assertEqual((s.turns, s.turn_tool_calls, s.active), (1, 1, False))
        self.assertEqual(s.turn_usage.total_tokens, 282000)
        self.assertEqual((s.avg_ttft_ms, s.avg_turn_ms), (1200, 5000))


class SettingsParsing(unittest.TestCase):
    def test_parse_size_legacy_and_linear(self):
        self.assertEqual(parse_size('s'), 0.85)
        self.assertEqual(parse_size('M'), 1.0)
        self.assertEqual(parse_size('l'), 1.2)
        self.assertEqual(parse_size(1.08), 1.08)
        self.assertEqual(parse_size('0.92'), 0.92)
        self.assertEqual(parse_size(0.1), SIZE_MIN)
        self.assertEqual(parse_size(9.9), SIZE_MAX)
        for bad in (None, True, False, 'abc', float('nan'), []):
            self.assertEqual(parse_size(bad), 1.0)

    def test_parse_opacity_zero_to_hundred(self):
        self.assertEqual(parse_opacity(0), 0)
        self.assertEqual(parse_opacity('0%'), 0)
        self.assertEqual(parse_opacity(100), 100)
        self.assertEqual(parse_opacity(64.6), 65)
        self.assertEqual(parse_opacity(-10), 0)
        self.assertEqual(parse_opacity(150), 100)
        for bad in (None, True, False, 'abc', float('nan'), {}):
            self.assertEqual(parse_opacity(bad), 100)


class CostCalculation(unittest.TestCase):
    def test_all_codex_picker_models_and_aliases(self):
        expected = {
            'gpt-6.1-sol': (2.00, 0.10, 10.00),
            'GPT-6.1 Sol': (2.00, 0.10, 10.00),
            'gpt-6-astra': (10.00, 1.00, 50.00),
            'GPT-6 Astra': (10.00, 1.00, 50.00),
            'gpt-6.1-terra': (1.00, 0.05, 5.00),
            'GPT-6.1 Terra': (1.00, 0.05, 5.00),
            'gpt-6-sol': (2.00, 0.20, 10.00),
            'GPT-6 Sol': (2.00, 0.20, 10.00),
            'gpt-6-luna': (0.10, 0.01, 0.50),
            'GPT-6 Luna': (0.10, 0.01, 0.50),
            'gpt-5.6-sol': (4.00, 0.40, 20.00),
            'GPT-5.6 Sol': (4.00, 0.40, 20.00),
            'gpt-5.6-terra': (2.00, 0.20, 12.00),
            'GPT-5.6 Terra': (2.00, 0.20, 12.00),
            'gpt-5.6-luna': (0.20, 0.02, 1.20),
            'GPT-5.6 Luna': (0.20, 0.02, 1.20),
            'gpt-reserve': (0.20, 0.02, 1.20),
            'codex-auto-review': (0.20, 0.02, 1.20),
            'gpt-5.4': (2.50, 0.25, 15.00),
            'gpt-5.3-codex': (1.75, 0.175, 14.00),
            'gpt-5-mini': (0.25, 0.025, 2.00),
            'codex-mini-latest': (1.50, 0.375, 6.00),
        }
        for slug, triple in expected.items():
            r = resolve_rate(slug)
            self.assertIsNotNone(r, slug)
            self.assertEqual((r.inp, r.cached, r.out), triple, slug)

    def test_multi_model_and_long_context_cost(self):
        m = SessionMetrics()
        for raw in [
            line('2026-10-31T00:00:00.000Z', 'event_msg', {
                'type': 'thread_settings_applied',
                'thread_settings': {'model': 'gpt-6.1-sol', 'service_tier': 'default'},
            }),
            line('2026-10-31T00:00:01.000Z', 'event_msg', {'type': 'task_started'}),
            # Request 1 on gpt-6.1-sol ($2 in / $0.10 cached / $10 out per 1M):
            # 100k uncached ($0.20) + 100k cached ($0.01) + 10k out ($0.10) = $0.31, saved $0.19
            line('2026-10-31T00:00:02.000Z', 'token_usage_record', {
                'response_id': 'r1',
                'usage': usage(200_000, 100_000, 10_000),
                'turn_token_usage': usage(200_000, 100_000, 10_000),
                'thread_token_usage': usage(200_000, 100_000, 10_000),
            }),
            # Turn 2 switches to gpt-6-astra ($10 in / $1 cached / $50 out) AND >272K long-context (2x in, 1.5x out):
            # 300k input (250k cached, 50k uncached), 4k output:
            # uncached: 0.05M * $20 = $1.00; cached: 0.25M * $2 = $0.50; out: 0.004M * $75 = $0.30 -> $1.80, saved $4.50
            line('2026-10-31T00:00:03.000Z', 'event_msg', {'type': 'task_started'}),
            line('2026-10-31T00:00:03.100Z', 'turn_context', {'model': 'gpt-6-astra'}),
            line('2026-10-31T00:00:05.000Z', 'token_usage_record', {
                'response_id': 'r2',
                'usage': usage(300_000, 250_000, 4_000),
                'turn_token_usage': usage(300_000, 250_000, 4_000),
                'thread_token_usage': usage(500_000, 350_000, 14_000),
            }),
        ]:
            m.feed(raw)
        s = m.snapshot()
        self.assertAlmostEqual(s.cost_usd, 0.31 + 1.80, places=6)
        self.assertAlmostEqual(s.cache_saved_usd, 0.19 + 4.50, places=6)
        self.assertAlmostEqual(s.turn_cost_usd, 1.80, places=6)
        self.assertAlmostEqual(s.total_cost_usd, 2.11, places=6)
        self.assertEqual((s.fast_requests, s.long_context_requests), (0, 1))

    def test_fast_mode_long_context_stacking_and_reset(self):
        # Exact 272K boundary is short-context (1x); 272,001 triggers >272K (2x in, 1.5x out)
        at_272k, _ = cost_for_usage(Usage(272_000, 0, 10_000), 'gpt-6.1-sol')
        self.assertAlmostEqual(at_272k, 0.272 * 2.0 + 0.01 * 10.0, places=6)
        over_272k, _ = cost_for_usage(Usage(272_001, 0, 10_000), 'gpt-6.1-sol')
        self.assertAlmostEqual(over_272k, 0.272001 * 4.0 + 0.01 * 15.0, places=6)

        # Flat-context legacy models (gpt-4.1, o3, gpt-5.3-codex) do not apply >272K cliff
        flat_cost, _ = cost_for_usage(Usage(300_000, 0, 10_000), 'gpt-4.1')
        self.assertAlmostEqual(flat_cost, 0.3 * 2.0 + 0.01 * 8.0, places=6)

        # Fast ('priority') + >272K stacks: 4x input/cached, 3x output on gpt-6.1-sol ($8 / $0.40 / $30)
        m = SessionMetrics()
        for raw in [
            line('2026-10-31T00:00:00.000Z', 'event_msg', {
                'type': 'thread_settings_applied',
                'thread_settings': {'model': 'gpt-6.1-sol', 'service_tier': 'priority', 'reasoning_effort': 'high'},
            }),
            line('2026-10-31T00:00:01.000Z', 'token_usage_record', {
                'response_id': 'r1',
                'usage': usage(300_000, 200_000, 10_000),
                'thread_token_usage': usage(300_000, 200_000, 10_000),
            }),
            # User turns Fast OFF -> service_tier resets to None / 'default'
            line('2026-10-31T00:00:02.000Z', 'event_msg', {
                'type': 'thread_settings_applied',
                'thread_settings': {'model': 'gpt-6.1-sol', 'service_tier': None},
            }),
            line('2026-10-31T00:00:03.000Z', 'token_usage_record', {
                'response_id': 'r2',
                'usage': usage(100_000, 0, 10_000),
                'thread_token_usage': usage(400_000, 200_000, 20_000),
            }),
        ]:
            m.feed(raw)
        s = m.snapshot()
        # r1: uncached 0.1M * $8 ($0.80) + cached 0.2M * $0.40 ($0.08) + out 0.01M * $30 ($0.30) = $1.18
        # r2 (Fast OFF, <=272K): 0.1M * $2 ($0.20) + 0.01M * $10 ($0.10) = $0.30
        self.assertAlmostEqual(s.cost_usd, 1.18 + 0.30, places=6)
        self.assertEqual((s.fast_requests, s.long_context_requests), (1, 1))
        self.assertEqual(s.service_tier, 'default')
        self.assertEqual(s.effort, 'high')

    def test_overrides_and_formatting(self):
        r = resolve_rate('my-custom-model', {'my-custom-model': [3.0, 0.3, 15.0]})
        self.assertEqual((r.inp, r.cached, r.out), (3.0, 0.3, 15.0))
        self.assertEqual(fmt_usd(None), '—')
        self.assertEqual(fmt_usd(0.0), '$0.00')
        self.assertEqual(fmt_usd(0.004, compact=True), '<$0.01')
        self.assertEqual(fmt_usd(0.004, compact=False), '$0.004')
        self.assertEqual(fmt_usd(35.774), '$35.77')
        self.assertEqual(fmt_usd(1250.5, compact=True), '$1.25K')
        self.assertEqual(fmt_rate('gpt-6.1-sol'), '$2 / $0.1 / $10 · 1M')
        self.assertEqual(fmt_rate('gpt-6.1-sol', 'priority'), '$4 / $0.2 / $20 · 1M (Fast 2×)')
        self.assertEqual(fmt_rate('gpt-6.1-sol', 'default', 300_000), '$4 / $0.2 / $15 · 1M (>272K)')
        self.assertEqual(fmt_rate('gpt-6.1-sol', 'priority', 300_000), '$8 / $0.4 / $30 · 1M (Fast 2× · >272K)')


if __name__ == '__main__':
    unittest.main()
