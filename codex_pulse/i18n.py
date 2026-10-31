"""UI strings and locale-aware formatting (zh / en)."""
from __future__ import annotations

import time

LANGS = ('zh', 'en')

STRINGS = {
    'zh': {
        'strip.ctx': '上下文', 'strip.tok': 'Tokens', 'strip.cost': '成本', 'strip.cache': '缓存', 'strip.tps': 'TPS', 'strip.week': '周额度',
        'kpi.ctx': '上下文', 'kpi.cost': '会话成本', 'kpi.cache': '缓存命中', 'kpi.tps': '会话 TPS', 'kpi.week': '周额度',
        'sec.session': '会话', 'sec.context': '上下文', 'sec.turn': '当前轮', 'sec.cost': '成本', 'sec.tokens': 'Token',
        'sec.speed': '速度', 'sec.quota': '额度',
        'row.model': '模型', 'row.perm': '权限', 'row.age': '时长', 'row.turns': '轮数', 'row.mode': '来源',
        'row.ctx_used': '用量', 'row.compact': '压缩',
        'row.c_state': '状态', 'row.c_elapsed': '已用时', 'row.c_tokens': '本轮 Token', 'row.c_tools': '工具调用',
        'row.cost_total': '会话总计', 'row.cost_turn': '本轮成本', 'row.cost_saved': '缓存已省',
        'row.cost_rate': '模型单价', 'row.cost_mult': '计费倍率',
        'row.t_total': '总计', 'row.t_in': '输入', 'row.t_cached': '缓存读取', 'row.t_out': '输出',
        'row.t_reason': '思考', 'row.t_rate': '缓存命中',
        'row.s_tps': '会话 TPS', 'row.s_last': '最近一次', 'row.s_ttft': '平均首字', 'row.s_turn': '平均每轮',
        'row.q_week': '周额度', 'row.q_short': '5 小时', 'row.q_credits': 'Credits', 'row.q_plan': '套餐',
        'val.pinned': '已固定', 'val.auto': '自动跟随最近活跃',
        'val.compact': '{n} 次 · 上次 {ago}', 'val.compact0': '0 次',
        'val.reason_share': '{n}（占输出 {p}%）',
        'val.tps': '{v} tok/s · {n} 次请求', 'val.last': '{v} tok/s · {tok} tok / {s}s',
        'val.generating': '生成中', 'val.idle': '空闲',
        'val.quota': '已用 {p}% · {t}重置', 'val.not_returned': '当前套餐未返回',
        'val.ctx_of': '{used} / {max}', 'val.reset_in': '{t}重置', 'val.kpi_last': '最近一次 {v}',
        'val.cost_api': '{v}（API 等效）', 'val.cost_sub': '{v}（主 {m} + {n} 子代理 {s}）',
        'val.cost_saved': '{v}（省 {p}%）', 'val.kpi_saved': '缓存省 {v}', 'val.kpi_sub': '含 {n} 个子代理',
        'val.api_equiv': 'API 等效',
        'val.mult_std': '标准 1×', 'val.mult_fast': 'Fast 2×（{n} 次）', 'val.mult_long': '>272K（{n} 次）',
        'val.unnamed': '(未命名会话)', 'val.searching': '正在查找 Codex 会话…', 'val.no_session': '未找到 Codex 会话记录',
        'foot.theme': '外观', 'foot.lang': '语言',
        'theme.system': '系统', 'theme.light': '浅色', 'theme.dark': '深色',
        'hint': '单击固定面板 · 拖动移动 · 右键切换会话',
        'menu.session': '选择会话', 'menu.auto': '自动：跟随最近活跃的会话', 'menu.none': '（没有读到会话列表）',
        'menu.theme': '外观', 'menu.theme.system': '跟随系统', 'menu.theme.light': '浅色', 'menu.theme.dark': '深色',
        'menu.lang': '语言 / Language', 'menu.reveal': '打开会话文件', 'menu.reset': '重置位置',
        'menu.quit': '退出 Codex Pulse',
        'menu.size': '大小', 'size.s': '小', 'size.m': '中', 'size.l': '大', 'menu.opacity': '透明度',
        'msg.running': 'Codex Pulse 已经在运行了。\n\n状态条只在 Codex 窗口可见时显示；要退出，在状态条上点右键 →「退出 Codex Pulse」。',
        'dur.d': '{d}天{h}小时', 'dur.h': '{h}小时{m}分', 'dur.m': '{m}分{s}秒', 'dur.s': '{s}秒',
        'ago': '{x}前', 'until': '{x}后',
    },
    'en': {
        'strip.ctx': 'Context', 'strip.tok': 'Tokens', 'strip.cost': 'Cost', 'strip.cache': 'Cache', 'strip.tps': 'TPS', 'strip.week': 'Weekly',
        'kpi.ctx': 'Context', 'kpi.cost': 'Session cost', 'kpi.cache': 'Cache hit', 'kpi.tps': 'Session TPS', 'kpi.week': 'Weekly quota',
        'sec.session': 'Session', 'sec.context': 'Context', 'sec.turn': 'Current turn', 'sec.cost': 'Cost', 'sec.tokens': 'Tokens',
        'sec.speed': 'Speed', 'sec.quota': 'Quota',
        'row.model': 'Model', 'row.perm': 'Permissions', 'row.age': 'Age', 'row.turns': 'Turns', 'row.mode': 'Source',
        'row.ctx_used': 'Used', 'row.compact': 'Compactions',
        'row.c_state': 'State', 'row.c_elapsed': 'Elapsed', 'row.c_tokens': 'Turn tokens', 'row.c_tools': 'Tool calls',
        'row.cost_total': 'Session', 'row.cost_turn': 'Current turn', 'row.cost_saved': 'Cache saved',
        'row.cost_rate': 'Model rate', 'row.cost_mult': 'Multipliers',
        'row.t_total': 'Total', 'row.t_in': 'Input', 'row.t_cached': 'Cached input', 'row.t_out': 'Output',
        'row.t_reason': 'Reasoning', 'row.t_rate': 'Cache hit',
        'row.s_tps': 'Session TPS', 'row.s_last': 'Last request', 'row.s_ttft': 'Avg TTFT', 'row.s_turn': 'Avg turn',
        'row.q_week': 'Weekly', 'row.q_short': '5-hour', 'row.q_credits': 'Credits', 'row.q_plan': 'Plan',
        'val.pinned': 'Pinned', 'val.auto': 'Auto: most recent',
        'val.compact': '{n} · last {ago}', 'val.compact0': 'none',
        'val.reason_share': '{n} ({p}% of output)',
        'val.tps': '{v} tok/s · {n} requests', 'val.last': '{v} tok/s · {tok} tok / {s}s',
        'val.generating': 'Generating', 'val.idle': 'Idle',
        'val.quota': '{p}% used · resets {t}', 'val.not_returned': 'not reported for this plan',
        'val.ctx_of': '{used} / {max}', 'val.reset_in': 'resets {t}', 'val.kpi_last': 'last {v}',
        'val.cost_api': '{v} (API equiv.)', 'val.cost_sub': '{v} (main {m} + {n} sub {s})',
        'val.cost_saved': '{v} ({p}% saved)', 'val.kpi_saved': 'saved {v}', 'val.kpi_sub': 'incl. {n} subagents',
        'val.api_equiv': 'API equiv.',
        'val.mult_std': 'Standard 1×', 'val.mult_fast': 'Fast 2× ({n})', 'val.mult_long': '>272K ({n})',
        'val.unnamed': '(untitled)', 'val.searching': 'Looking for Codex sessions…', 'val.no_session': 'No Codex session found',
        'foot.theme': 'Theme', 'foot.lang': 'Language',
        'theme.system': 'System', 'theme.light': 'Light', 'theme.dark': 'Dark',
        'hint': 'Click to pin · drag to move · right-click for sessions',
        'menu.session': 'Session', 'menu.auto': 'Auto: follow most recent session', 'menu.none': '(no sessions found)',
        'menu.theme': 'Theme', 'menu.theme.system': 'Follow system', 'menu.theme.light': 'Light', 'menu.theme.dark': 'Dark',
        'menu.lang': 'Language / 语言', 'menu.reveal': 'Open session file', 'menu.reset': 'Reset position',
        'menu.quit': 'Quit Codex Pulse',
        'menu.size': 'Size', 'size.s': 'S', 'size.m': 'M', 'size.l': 'L', 'menu.opacity': 'Opacity',
        'msg.running': 'Codex Pulse is already running.\n\nThe strip only shows while the Codex window is visible. '
                       'To quit, right-click the strip → "Quit Codex Pulse".',
        'dur.d': '{d}d {h}h', 'dur.h': '{h}h {m}m', 'dur.m': '{m}m {s}s', 'dur.s': '{s}s',
        'ago': '{x} ago', 'until': 'in {x}',
    },
}


class I18n:
    def __init__(self, lang: str = 'zh'):
        self.lang = lang if lang in LANGS else 'zh'

    def t(self, key: str, **kw) -> str:
        text = STRINGS[self.lang].get(key) or STRINGS['zh'].get(key) or key
        return text.format(**kw) if kw else text

    def duration(self, seconds: float | None) -> str:
        if seconds is None or seconds < 0:
            return '—'
        s = int(seconds)
        d, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        if d:
            return self.t('dur.d', d=d, h=h)
        if h:
            return self.t('dur.h', h=h, m=m)
        if m:
            return self.t('dur.m', m=m, s=s)
        return self.t('dur.s', s=s)

    def ago(self, ts: float | None) -> str:
        return '—' if ts is None else self.t('ago', x=self.duration(time.time() - ts))

    def until(self, ts: float | None) -> str:
        return '—' if ts is None else self.t('until', x=self.duration(ts - time.time()))


def system_lang() -> str:
    import locale
    try:
        code = locale.getlocale()[0] or ''
    except ValueError:
        code = ''
    return 'zh' if code.lower().startswith(('zh', 'chinese')) else 'en'
