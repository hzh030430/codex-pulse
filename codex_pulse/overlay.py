"""Status strip + detail panel docked to the Codex Desktop window.

Docking is event driven (WinEvent hooks) and z-order based: the strip sits
directly above the Codex window instead of being top-most, so it stays visible
whenever Codex is visible, focused or not, and is covered by whatever covers
Codex.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from . import win32
from .i18n import I18n, system_lang
from .menu import PopupMenu
from .metrics import Snapshot, human
from .pricing import fmt_rate, fmt_usd, is_fast_tier
from .watcher import SessionWatcher, View, codex_home

DATA_TICK_MS = 1000
PUMP_MS = 30
SAFETY_TICK_MS = 600
WINDOW_RESCAN_S = 3.0
THEME_RECHECK_S = 5.0

log = logging.getLogger('codex_pulse')

PALETTES = {
    'dark': dict(bg='#1c1c1f', card='#26262b', border='#3a3a40', text='#f4f4f5', muted='#a1a1aa',
                 faint='#71717a', sep='#3a3a40', accent='#60a5fa', good='#34d399', warn='#fbbf24',
                 bad='#f87171', track='#3a3a40', seg='#26262b', seg_on='#3f3f46', seg_text_on='#f4f4f5',
                 hover='#2c2c32'),
    'light': dict(bg='#ffffff', card='#f4f4f5', border='#dcdce0', text='#18181b', muted='#71717a',
                  faint='#a1a1aa', sep='#e4e4e7', accent='#2563eb', good='#059669', warn='#d97706',
                  bad='#dc2626', track='#e4e4e7', seg='#f4f4f5', seg_on='#ffffff', seg_text_on='#18181b',
                  hover='#f1f1f3'),
}
THEMES = ('system', 'light', 'dark')
SIZE_MIN, SIZE_MAX = 0.75, 1.25
LEGACY_SIZES = {'s': 0.85, 'm': 1.0, 'l': 1.2}


def parse_size(val) -> float:
    if isinstance(val, str):
        k = val.strip().lower()
        if k in LEGACY_SIZES:
            return LEGACY_SIZES[k]
        try:
            val = float(k)
        except ValueError:
            return 1.0
    if isinstance(val, bool) or not isinstance(val, (int, float)) or val != val:
        return 1.0
    return round(min(max(float(val), SIZE_MIN), SIZE_MAX), 2)


def parse_opacity(val) -> int:
    if isinstance(val, str):
        try:
            val = float(val.strip().rstrip('%'))
        except ValueError:
            return 100
    if isinstance(val, bool) or not isinstance(val, (int, float)) or val != val:
        return 100
    return min(max(round(val), 0), 100)


# ---------------------------------------------------------------- settings
def settings_path() -> Path:
    return Path(os.environ.get('APPDATA', Path.home())) / 'CodexPulse' / 'settings.json'


def load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    try:
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def pct(ratio: float | None, digits: int = 0) -> str:
    return '—' if ratio is None else f'{ratio * 100:.{digits}f}%'


class Overlay:
    DEFAULT_OFFSET = (16, 10)  # logical px from Codex's bottom-right corner
    SIZE_MIN = SIZE_MIN
    SIZE_MAX = SIZE_MAX

    def __init__(self, watcher: SessionWatcher):
        self.watcher = watcher
        self.settings = load_settings()
        if isinstance(self.settings.get('pricing'), dict):
            self.watcher.price_overrides = self.settings['pricing']
        self.offset = tuple(self.settings.get('offset', self.DEFAULT_OFFSET))
        self.theme_pref = self.settings.get('theme') if self.settings.get('theme') in THEMES else 'system'
        self.size_scale = parse_size(self.settings.get('size'))
        self.opacity = parse_opacity(self.settings.get('opacity'))
        self._size_timer = None
        self._pending_size: float | None = None
        self.i18n = I18n(self.settings.get('lang') or system_lang())
        self.win11 = win32.is_windows11()
        self.view = View(Snapshot())
        self.codex_hwnd = 0
        self.codex_pid = 0
        self.last_scan = -1e9
        self.theme = None
        self.theme_checked = -1e9
        self.dpi = 1.0
        self.visible = False
        self.panel_visible = False
        self.panel_pinned = False
        self.drag = None
        self.dragged = False
        self.sync_pending = False
        self.cache: dict = {}
        self.themed: list = []

        self.root = tk.Tk()
        self.root.report_callback_exception = lambda *exc: log.error('Tk callback failed', exc_info=exc)
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.title('Codex Pulse')
        self.panel = tk.Toplevel(self.root)
        self.panel.withdraw()
        self.panel.overrideredirect(True)

        self.fonts = {name: tkfont.Font(root=self.root) for name in
                      ('label', 'value', 'body', 'head', 'title', 'sub', 'kpi', 'seg')}
        self._configure_fonts()
        self.build()
        self.popup = PopupMenu(self)

        self.root.deiconify()
        self.root.update_idletasks()
        self.hwnd = win32.root_window(int(self.root.winfo_id()))
        win32.style_overlay(self.hwnd)
        win32.show_no_activate(self.hwnd, False)
        self.panel.deiconify()
        self.panel.update_idletasks()
        self.panel_hwnd = win32.root_window(int(self.panel.winfo_id()))
        win32.style_overlay(self.panel_hwnd)
        win32.show_no_activate(self.panel_hwnd, False)

        self.events = win32.WinEvents(self.on_win_event)
        self.apply_theme(force=True)
        self.apply_opacity()

    # ================================================================ helpers
    @property
    def t(self):
        return self.i18n.t

    @property
    def scale(self) -> float:
        """Monitor DPI x user size scale."""
        return self.dpi * self.size_scale

    def px(self, v: float) -> int:
        return max(1, round(v * self.scale))

    def _configure_fonts(self) -> None:
        zh = self.i18n.lang == 'zh'
        text = 'Microsoft YaHei UI' if zh else 'Segoe UI'
        cjk = 'Microsoft YaHei UI'  # session titles are often Chinese, whatever the UI language
        num = 'Segoe UI Semibold'
        spec = {
            'label': (text, 11, 'normal'), 'value': (num, 12, 'normal'), 'body': (text, 12, 'normal'),
            'head': (text, 11, 'bold'), 'title': (cjk, 14, 'bold'), 'sub': (text, 11, 'normal'),
            'kpi': (num, 20, 'normal'), 'seg': (text, 11, 'normal'),
        }
        for name, (family, size, weight) in spec.items():
            # Negative size = pixels, so text follows the Codex monitor's DPI.
            self.fonts[name].configure(family=family, size=-max(9, round(size * self.scale)), weight=weight)

    def W(self, cls, parent, roles: dict, **kw):
        """Create a widget and register its palette roles (bg / fg / ...)."""
        w = cls(parent, **kw)
        self.themed.append((w, roles))
        return w

    def L(self, parent, text='', font='body', fg='text', bg='bg', **kw) -> tk.Label:
        return self.W(tk.Label, parent, {'bg': bg, 'fg': fg}, text=text, font=self.fonts[font],
                      bd=0, padx=0, pady=0, **kw)

    def F(self, parent, bg='bg', **kw) -> tk.Frame:
        return self.W(tk.Frame, parent, {'bg': bg}, bd=0, **kw)

    def C(self, parent, w, h, bg='bg') -> tk.Canvas:
        return self.W(tk.Canvas, parent, {'bg': bg}, width=w, height=h, bd=0, highlightthickness=0)

    # ================================================================ build
    def build(self) -> None:
        # Keep Toplevels (panel, popup menu); rebuild the strip and the panel's content.
        for child in list(self.root.winfo_children()) + list(self.panel.winfo_children()):
            if child.winfo_class() != 'Toplevel':
                child.destroy()
        self.themed = []
        self.cache = {}
        self._build_strip()
        self._build_panel()

    def _bind_strip(self, w) -> None:
        w.bind('<ButtonPress-1>', self.on_press)
        w.bind('<B1-Motion>', self.on_drag)
        w.bind('<ButtonRelease-1>', self.on_release)
        w.bind('<Button-3>', self.on_menu)
        w.bind('<Enter>', self.on_enter)
        w.bind('<Leave>', self.on_leave)

    def _build_strip(self) -> None:
        P = self.px
        border = 0 if self.win11 else 1
        self.strip = self.W(tk.Frame, self.root, {'bg': 'bg', 'highlightbackground': 'border',
                                                  'highlightcolor': 'border'}, bd=0, highlightthickness=border)
        self.strip.pack(fill='both', expand=True)
        row = self.F(self.strip)
        row.pack(padx=P(12), pady=P(6))
        widgets = [self.strip, row]
        self.icon = self.C(row, P(14), P(14))
        self.icon.pack(side='left', padx=(0, P(10)))
        widgets.append(self.icon)
        self.strip_vals, self.strip_bars = {}, {}
        for i, key in enumerate(('ctx', 'tok', 'cost', 'cache', 'tps', 'week')):
            if i:
                sep = self.F(row, bg='sep', width=1, height=P(14))
                sep.pack(side='left', padx=P(10))
                widgets.append(sep)
            lab = self.L(row, self.t(f'strip.{key}'), font='label', fg='muted')
            lab.pack(side='left', padx=(0, P(5)))
            val = self.L(row, '—', font='value')
            val.pack(side='left')
            widgets += [lab, val]
            self.strip_vals[key] = val
            if key in ('ctx', 'week'):
                bar = self.C(row, P(28), P(4))
                bar.pack(side='left', padx=(P(6), 0))
                self.strip_bars[key] = bar
                widgets.append(bar)
        for w in widgets:
            self._bind_strip(w)

    def _build_panel(self) -> None:
        P, t = self.px, self.t
        border = 0 if self.win11 else 1
        frame = self.W(tk.Frame, self.panel, {'bg': 'bg', 'highlightbackground': 'border',
                                              'highlightcolor': 'border'}, bd=0, highlightthickness=border)
        frame.pack(fill='both', expand=True)
        body = self.F(frame)
        body.pack(padx=P(16), pady=P(14), fill='both')
        self.panel_widgets = [frame, body]
        self.rows = {}

        # header
        self.p_title = self.L(body, '—', font='title', anchor='w', justify='left', wraplength=P(580))
        self.p_title.pack(fill='x')
        self.p_sub = self.L(body, '—', font='sub', fg='muted', anchor='w', justify='left', wraplength=P(580))
        self.p_sub.pack(fill='x', pady=(P(2), P(12)))

        # KPI cards
        cards = self.F(body)
        cards.pack(fill='x')
        self.kpi = {}
        for i, key in enumerate(('ctx', 'cost', 'cache', 'tps', 'week')):
            card = self.F(cards, bg='card')
            card.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else P(8), 0))
            cards.grid_columnconfigure(i, weight=1, uniform='kpi')
            inner = self.F(card, bg='card')
            inner.pack(fill='both', padx=P(11), pady=P(10))
            lab = self.L(inner, t(f'kpi.{key}'), font='label', fg='muted', bg='card', anchor='w')
            lab.pack(fill='x')
            val = self.L(inner, '—', font='kpi', bg='card', anchor='w')
            val.pack(fill='x', pady=(P(2), P(4)))
            bar = self.C(inner, P(90), P(4), bg='card')
            bar.pack(anchor='w', pady=(0, P(5)))
            sub = self.L(inner, '—', font='sub', fg='faint', bg='card', anchor='w')
            sub.pack(fill='x')
            self.kpi[key] = (val, bar, sub)
            self.panel_widgets += [card, inner, lab, val, bar, sub]

        # detail sections
        details = self.F(body)
        details.pack(fill='x', pady=(P(14), 0))
        columns = [
            [('session', ['perm', 'age', 'turns', 'mode']),
             ('context', ['ctx_used', 'compact']),
             ('turn', ['c_state', 'c_elapsed', 'c_tokens', 'c_tools']),
             ('cost', ['cost_total', 'cost_turn', 'cost_saved', 'cost_rate', 'cost_mult'])],
            [('tokens', ['t_total', 't_in', 't_cached', 't_out', 't_reason']),
             ('speed', ['s_last', 's_ttft', 's_turn']),
             ('quota', ['q_week', 'q_short', 'q_credits', 'q_plan'])],
        ]
        for ci, sections in enumerate(columns):
            col = self.F(details)
            col.grid(row=0, column=ci, sticky='nw', padx=(0, P(28)) if ci == 0 else 0)
            details.grid_columnconfigure(ci, weight=1)
            self.panel_widgets.append(col)
            r = 0
            for sec, keys in sections:
                head = self.L(col, t(f'sec.{sec}'), font='head', fg='faint', anchor='w')
                head.grid(row=r, column=0, columnspan=2, sticky='w', pady=(P(10) if r else 0, P(4)))
                self.panel_widgets.append(head)
                r += 1
                for key in keys:
                    k = self.L(col, t(f'row.{key}'), font='body', fg='muted', anchor='w')
                    v = self.L(col, '—', font='body', anchor='w', justify='left')
                    k.grid(row=r, column=0, sticky='nw', padx=(0, P(14)), pady=P(1))
                    v.grid(row=r, column=1, sticky='w', pady=P(1))
                    self.rows[key] = v
                    self.panel_widgets += [k, v]
                    r += 1

        # footer: hint + segmented controls
        line = self.F(body, bg='sep', height=1)
        line.pack(fill='x', pady=(P(14), P(10)))
        foot = self.F(body)
        foot.pack(fill='x')
        hint = self.L(foot, t('hint'), font='sub', fg='faint', anchor='w')
        hint.pack(side='left')
        self.panel_widgets += [line, foot, hint]
        self.seg_items = []
        right = self.F(foot)
        right.pack(side='right')
        self.panel_widgets.append(right)
        self._segmented(right, 'lang', [('zh', '中文'), ('en', 'EN')], self.i18n.lang, self.set_lang)
        spacer = self.F(right, width=P(10))
        spacer.pack(side='right')
        self._segmented(right, 'theme', [(k, t(f'theme.{k}')) for k in THEMES], self.theme_pref, self.set_theme)

        for w in self.panel_widgets:
            w.bind('<Leave>', self.on_leave)
            w.bind('<Button-3>', self.on_menu)

    def _segmented(self, parent, group, options, current, command) -> None:
        P = self.px
        box = self.F(parent, bg='seg')
        box.pack(side='right')
        inner = self.F(box, bg='seg')
        inner.pack(padx=P(2), pady=P(2))
        self.panel_widgets += [box, inner]
        for value, label in options:
            on = value == current
            roles = {'bg': 'seg_on' if on else 'seg', 'fg': 'seg_text_on' if on else 'muted'}
            item = self.W(tk.Label, inner, roles, text=label, font=self.fonts['seg'], bd=0,
                          padx=P(8), pady=P(2), cursor='hand2')
            item.pack(side='left')
            item.bind('<Button-1>', lambda _e, v=value: command(v))
            self.panel_widgets.append(item)

    # ================================================================ theme / language
    def set_theme(self, value: str) -> None:
        self.theme_pref = value if value in THEMES else 'system'
        self.settings['theme'] = self.theme_pref
        save_settings(self.settings)
        self.rebuild()

    def set_size(self, value: float | str, save: bool = True) -> None:
        v = parse_size(value)
        if not save:
            self._pending_size = v
            if self._size_timer is None:
                self._size_timer = self.root.after(25, self._apply_pending_size)
            return
        if self._size_timer is not None:
            try:
                self.root.after_cancel(self._size_timer)
            except tk.TclError:
                pass
            self._size_timer = None
        self._pending_size = None
        if abs(v - self.size_scale) >= 0.005:
            self.size_scale = v
            self._configure_fonts()
            self.rebuild()
        if self.settings.get('size') != self.size_scale:
            self.settings['size'] = self.size_scale
            save_settings(self.settings)

    def _apply_pending_size(self) -> None:
        self._size_timer = None
        v = self._pending_size
        self._pending_size = None
        if v is None or abs(v - self.size_scale) < 0.005:
            return
        self.size_scale = v
        self._configure_fonts()
        self.rebuild()

    def set_opacity(self, value: int | float, save: bool = True) -> None:
        v = parse_opacity(value)
        if v != self.opacity:
            self.opacity = v
            self.apply_opacity()
        if save and self.settings.get('opacity') != self.opacity:
            self.settings['opacity'] = self.opacity
            save_settings(self.settings)

    def apply_opacity(self) -> None:
        # Keep Win32 bAlpha >= 1 (~0.004): visually 0% transparent, yet still
        # receives right-clicks so setting opacity to 0 never locks the user out.
        alpha = max(0.004, self.opacity / 100)
        for win in (self.root, self.panel):
            try:
                win.attributes('-alpha', alpha)
            except tk.TclError:
                pass

    def set_lang(self, value: str) -> None:
        if value == self.i18n.lang:
            return
        self.i18n = I18n(value)
        self.settings['lang'] = self.i18n.lang
        save_settings(self.settings)
        self._configure_fonts()
        self.rebuild()

    def rebuild(self) -> None:
        pinned = self.panel_pinned
        self.build()
        self.apply_theme(force=True)
        self.render()
        if self.panel_visible:
            self.render_panel()
            self._position_panel()
        self.panel_pinned = pinned
        if not self.codex_hwnd:
            self.root.update_idletasks()
            x, y = self.root.winfo_x(), self.root.winfo_y()
            self.root.geometry(f'{self.root.winfo_reqwidth()}x{self.root.winfo_reqheight()}+{x}+{y}')
        self.sync()

    def apply_theme(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.theme_checked < THEME_RECHECK_S:
            return
        self.theme_checked = now
        theme = self.theme_pref if self.theme_pref != 'system' else (
            'light' if win32.apps_use_light_theme() else 'dark')
        if theme == self.theme and not force:
            return
        self.theme = theme
        pal = self.pal = PALETTES[theme]
        for w, roles in self.themed:
            try:
                w.configure(**{opt: pal[role] for opt, role in roles.items()})
            except tk.TclError:
                pass
        if self.win11:
            for h in (getattr(self, 'hwnd', 0), getattr(self, 'panel_hwnd', 0)):
                if h:
                    win32.set_border_color(h, pal['border'])
        self._draw_icon()
        self.cache.clear()
        self.render()
        if self.panel_visible:
            self.render_panel()

    def _draw_icon(self) -> None:
        c, P = self.icon, self.px
        c.delete('all')
        s = P(14)
        pts = [(0.0, 0.55), (0.28, 0.55), (0.38, 0.25), (0.52, 0.85), (0.64, 0.12), (0.74, 0.55), (1.0, 0.55)]
        c.create_line(*[v for x, y in pts for v in (x * (s - 2) + 1, y * (s - 2) + 1)],
                      fill=self.pal['accent'], width=max(1.5, 1.6 * self.scale), capstyle='round',
                      joinstyle='round', smooth=False)

    # ================================================================ render
    def _set(self, widget: tk.Label, text: str, fg: str | None = None) -> None:
        state = (text, fg)
        if self.cache.get(id(widget)) == state:
            return
        self.cache[id(widget)] = state
        widget.configure(text=text, **({'fg': fg} if fg else {}))

    def _bar(self, canvas: tk.Canvas, ratio: float | None, color: str, blank: bool = False) -> None:
        state = ('bar', ratio and round(ratio, 3), color, self.theme, canvas.winfo_reqwidth(), blank)
        if self.cache.get(id(canvas)) == state:
            return
        self.cache[id(canvas)] = state
        canvas.delete('all')
        if blank:
            return
        w, h = int(canvas.cget('width')), int(canvas.cget('height'))
        canvas.create_rectangle(0, 0, w, h, fill=self.pal['track'], width=0)
        if ratio:
            canvas.create_rectangle(0, 0, max(2, round(w * ratio)), h, fill=color, width=0)

    def level(self, ratio: float | None, warn: float, alert: float, neutral: str = 'text') -> str:
        """Higher is worse (context, quota)."""
        pal = self.pal
        if ratio is None:
            return pal['faint']
        return pal['bad'] if ratio >= alert else pal['warn'] if ratio >= warn else pal[neutral]

    def cache_color(self, rate: float | None) -> str:
        pal = self.pal
        if rate is None:
            return pal['faint']
        return pal['good'] if rate >= 0.8 else pal['warn'] if rate >= 0.5 else pal['bad']

    def render(self) -> None:
        s, pal = self.view.snap, self.pal
        tot = s.totals
        ctx = s.context_ratio
        week = s.weekly.used_percent / 100 if s.weekly else None
        rate = tot.cache_rate if tot else None
        cost = s.total_cost_usd
        V = self.strip_vals
        self._set(V['ctx'], pct(ctx), self.level(ctx, 0.7, 0.85))
        self._set(V['tok'], human(tot.total_tokens) if tot else '—', pal['text'])
        self._set(V['cost'], fmt_usd(cost, compact=True), pal['text'] if cost is not None else pal['faint'])
        self._set(V['cache'], pct(rate, 1), self.cache_color(rate))
        self._set(V['tps'], f'{s.session_tps:.1f}' if s.session_tps else '—', pal['text'])
        self._set(V['week'], pct(week), self.level(week, 0.8, 0.95))
        self._bar(self.strip_bars['ctx'], ctx, self.level(ctx, 0.7, 0.85, 'accent'))
        self._bar(self.strip_bars['week'], week, self.level(week, 0.8, 0.95, 'accent'))
        if self.panel_visible:
            self.render_panel()

    def render_panel(self) -> None:
        v, pal, R, t, i = self.view, self.pal, self.rows, self.t, self.i18n
        s, th = v.snap, v.thread
        tot = s.totals

        if s.error and not tot:
            self._set(self.p_title, s.error)
        else:
            self._set(self.p_title, th.title if th else (Path(s.path).name if s.path else '—'))
        project = (th.project if th else None) or (Path(s.cwd).name if s.cwd else None)
        model = s.model or (th.model if th else None)
        effort = s.effort or (th.effort if th else None)
        parts = [project, th.git_branch if th else None, model, effort,
                 'Fast' if is_fast_tier(s.service_tier) else None]
        self._set(self.p_sub, '  ·  '.join(p for p in parts if p) or '—')

        ctx = s.context_ratio
        week = s.weekly.used_percent / 100 if s.weekly else None
        rate = tot.cache_rate if tot else None
        total_cost = s.total_cost_usd
        total_saved = s.total_saved_usd
        val, bar, sub = self.kpi['ctx']
        self._set(val, pct(ctx), self.level(ctx, 0.7, 0.85))
        self._bar(bar, ctx, self.level(ctx, 0.7, 0.85, 'accent'))
        self._set(sub, t('val.ctx_of', used=human(s.context_used), max=human(s.context_window))
                  if s.context_window else '—')
        val, bar, sub = self.kpi['cost']
        self._set(val, fmt_usd(total_cost, compact=True), pal['text'] if total_cost is not None else pal['faint'])
        self._bar(bar, None, pal['accent'], blank=True)
        if s.subagent_count > 0:
            cost_sub = t('val.kpi_sub', n=s.subagent_count)
        elif total_saved and total_saved >= 0.01:
            cost_sub = t('val.kpi_saved', v=fmt_usd(total_saved, compact=True))
        else:
            cost_sub = t('val.api_equiv') if total_cost is not None else '—'
        self._set(sub, cost_sub)
        val, bar, sub = self.kpi['cache']
        self._set(val, pct(rate, 1), self.cache_color(rate))
        self._bar(bar, rate, self.cache_color(rate))
        self._set(sub, f'{human(tot.cached_input_tokens)} / {human(tot.input_tokens)}' if tot else '—')
        val, bar, sub = self.kpi['tps']
        self._set(val, f'{s.session_tps:.1f}' if s.session_tps else '—', pal['text'])
        self._bar(bar, None, pal['accent'], blank=True)
        self._set(sub, t('val.kpi_last', v=f'{s.last_tps:.1f}') if s.last_tps else '—')
        val, bar, sub = self.kpi['week']
        self._set(val, pct(week), self.level(week, 0.8, 0.95))
        self._bar(bar, week, self.level(week, 0.8, 0.95, 'accent'))
        self._set(sub, t('val.reset_in', t=i.until(s.weekly.resets_at)) if s.weekly else '—')

        perm = ' / '.join(x for x in (s.approval or (th.approval if th else None), s.sandbox) if x) or '—'
        self._set(R['perm'], perm)
        self._set(R['age'], i.duration(time.time() - s.started_at) if s.started_at else '—')
        self._set(R['turns'], str(s.turns) if s.turns else '—')
        self._set(R['mode'], t('val.pinned') if v.pinned else t('val.auto'),
                  pal['accent'] if v.pinned else pal['text'])
        self._set(R['ctx_used'], f'{s.context_used:,} / {s.context_window:,}'
                  if s.context_used and s.context_window else '—')
        self._set(R['compact'], t('val.compact', n=s.compactions, ago=i.ago(s.last_compaction_at))
                  if s.compactions else t('val.compact0'))

        self._set(R['c_state'], t('val.generating') if s.active else t('val.idle'),
                  pal['good'] if s.active else pal['muted'])
        self._set(R['c_elapsed'], i.duration(time.time() - s.turn_started_at)
                  if s.active and s.turn_started_at else '—')
        self._set(R['c_tokens'], human(s.turn_usage.total_tokens) if s.turn_usage else '—')
        self._set(R['c_tools'], str(s.turn_tool_calls) if s.turns else '—')

        if total_cost is None:
            self._set(R['cost_total'], '—')
        elif s.subagent_count > 0:
            self._set(R['cost_total'], t('val.cost_sub', v=fmt_usd(total_cost),
                                         m=fmt_usd(s.main_cost_usd or 0.0),
                                         n=s.subagent_count, s=fmt_usd(s.subagent_cost_usd)))
        else:
            self._set(R['cost_total'], t('val.cost_api', v=fmt_usd(total_cost)))
        tc = s.effective_turn_cost_usd
        self._set(R['cost_turn'], fmt_usd(tc) if tc is not None else '—')
        if total_saved and total_cost is not None and (total_cost + total_saved) > 0:
            save_pct = total_saved / (total_cost + total_saved) * 100
            self._set(R['cost_saved'], t('val.cost_saved', v=fmt_usd(total_saved), p=f'{save_pct:.0f}'), pal['good'])
        elif total_saved == 0.0 and total_cost is not None:
            self._set(R['cost_saved'], '$0.00', pal['muted'])
        else:
            self._set(R['cost_saved'], '—')
        overrides = self.settings.get('pricing') if isinstance(self.settings.get('pricing'), dict) else None
        self._set(R['cost_rate'], fmt_rate(model, s.service_tier, s.last_input_tokens, overrides=overrides))
        mult_parts = []
        if s.fast_requests:
            mult_parts.append(t('val.mult_fast', n=s.fast_requests))
        if s.long_context_requests:
            mult_parts.append(t('val.mult_long', n=s.long_context_requests))
        if mult_parts:
            self._set(R['cost_mult'], ' · '.join(mult_parts), pal['warn'])
        elif total_cost is not None:
            self._set(R['cost_mult'], t('val.mult_std'), pal['muted'])
        else:
            self._set(R['cost_mult'], '—')

        if tot:
            self._set(R['t_total'], f'{tot.total_tokens:,}')
            self._set(R['t_in'], f'{tot.input_tokens:,}')
            self._set(R['t_cached'], f'{tot.cached_input_tokens:,}')
            self._set(R['t_out'], f'{tot.output_tokens:,}')
            share = tot.reasoning_share
            self._set(R['t_reason'], t('val.reason_share', n=f'{tot.reasoning_output_tokens:,}', p=f'{share * 100:.0f}')
                      if share is not None else f'{tot.reasoning_output_tokens:,}')
        else:
            for k in ('t_total', 't_in', 't_cached', 't_out', 't_reason'):
                self._set(R[k], '—')

        self._set(R['s_last'], t('val.last', v=f'{s.last_tps:.1f}', tok=f'{s.last_output_tokens:,}',
                                 s=f'{s.last_seconds:.1f}') if s.last_tps else '—')
        self._set(R['s_ttft'], f'{s.avg_ttft_ms / 1000:.1f}s' if s.avg_ttft_ms else '—')
        self._set(R['s_turn'], i.duration(s.avg_turn_ms / 1000) if s.avg_turn_ms else '—')

        if s.weekly:
            self._set(R['q_week'], t('val.quota', p=f'{s.weekly.used_percent:.0f}', t=i.until(s.weekly.resets_at)),
                      self.level(week, 0.8, 0.95))
        else:
            self._set(R['q_week'], '—')
        if s.short:
            self._set(R['q_short'], t('val.quota', p=f'{s.short.used_percent:.0f}', t=i.until(s.short.resets_at)),
                      self.level(s.short.used_percent / 100, 0.8, 0.95))
        else:
            self._set(R['q_short'], t('val.not_returned'), pal['faint'])
        credits = s.credits
        if credits and credits != 'unlimited':
            try:
                credits = f'{float(credits):,.2f}'
            except ValueError:
                pass
        self._set(R['q_credits'], credits or '—')
        self._set(R['q_plan'], s.plan or '—')

    def data_tick(self) -> None:
        self.view = self.watcher.view()
        self.render()
        self.root.after(DATA_TICK_MS, self.data_tick)

    # ================================================================ panel
    def on_enter(self, _event=None) -> None:
        if self.drag is None:
            self.show_panel()

    def on_leave(self, _event=None) -> None:
        if not self.panel_pinned:
            self.root.after(150, self._hide_panel_if_outside)

    def _pointer_in(self, win: tk.Misc) -> bool:
        px, py = self.root.winfo_pointerxy()
        x, y = win.winfo_rootx(), win.winfo_rooty()
        return x <= px < x + win.winfo_width() and y <= py < y + win.winfo_height()

    def _hide_panel_if_outside(self) -> None:
        if self.panel_pinned or not self.panel_visible:
            return
        if self._pointer_in(self.root) or self._pointer_in(self.panel):
            return
        self.hide_panel()

    def show_panel(self) -> None:
        if not self.visible:
            return
        if not self.panel_visible:
            self.panel_visible = True
            self.render_panel()
        self._position_panel()
        win32.show_no_activate(self.panel_hwnd, True)
        self.sync()

    def hide_panel(self) -> None:
        self.panel_visible = False
        self.panel_pinned = False
        win32.show_no_activate(self.panel_hwnd, False)

    def _position_panel(self) -> None:
        self.panel.update_idletasks()
        pw, ph = self.panel.winfo_reqwidth(), self.panel.winfo_reqheight()
        x = self.root.winfo_x() + self.root.winfo_width() - pw
        y = self.root.winfo_y() - ph - self.px(8)
        rect = win32.frame_rect(self.codex_hwnd) if self.codex_hwnd else None
        if rect:
            x = max(rect[0] + self.px(8), x)
            if y < rect[1]:
                y = self.root.winfo_y() + self.root.winfo_height() + self.px(8)
        geo = f'{pw}x{ph}+{x}+{y}'
        if self.panel.geometry() != geo:
            self.panel.geometry(geo)

    # ================================================================ mouse
    def on_press(self, event) -> None:
        self.drag = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self.dragged = False

    def on_drag(self, event) -> None:
        if self.drag is None:
            return
        sx, sy, wx, wy = self.drag
        dx, dy = event.x_root - sx, event.y_root - sy
        if not self.dragged and abs(dx) + abs(dy) < 4:
            return
        if not self.dragged:
            self.dragged = True
            self.hide_panel()
        self.root.geometry(f'+{wx + dx}+{wy + dy}')

    def on_release(self, _event) -> None:
        if self.drag is None:
            return
        self.drag = None
        if not self.dragged:  # plain click: pin / unpin the panel
            if self.panel_pinned:
                self.hide_panel()
            else:
                self.panel_pinned = True
                self.show_panel()
            return
        rect = win32.frame_rect(self.codex_hwnd) if self.codex_hwnd else None
        if rect:
            right = rect[2] - (self.root.winfo_x() + self.root.winfo_width())
            bottom = rect[3] - (self.root.winfo_y() + self.root.winfo_height())
            self.offset = (round(right / self.dpi), round(bottom / self.dpi))
            self.settings['offset'] = list(self.offset)
            save_settings(self.settings)
        self.sync()

    def on_menu(self, event) -> None:
        if not self.panel_pinned:
            self.hide_panel()
        self.popup.show(event.x_root, event.y_root)

    def choose_session(self, thread_id: str | None) -> None:
        self.watcher.pin(thread_id)
        self.settings['pinned_thread'] = thread_id
        save_settings(self.settings)
        self.root.after(150, self.refresh_now)

    def refresh_now(self) -> None:
        self.view = self.watcher.view()
        self.render()

    def reset_position(self) -> None:
        self.offset = self.DEFAULT_OFFSET
        self.settings.pop('offset', None)
        save_settings(self.settings)
        self.sync()

    def reveal_session(self) -> None:
        path = self.view.snap.path
        if path and Path(path).exists():
            subprocess.Popen(['explorer.exe', '/select,', path])
        else:
            subprocess.Popen(['explorer.exe', str(codex_home() / 'sessions')])

    # ================================================================ docking
    def on_win_event(self, event: int, hwnd: int) -> None:
        # Runs inside Tk's own message dispatch: calling into Tcl here (even
        # root.after) corrupts _tkinter's thread state and kills the process.
        # Only set a flag; pump() picks it up on Tk's side.
        self.sync_pending = True

    def pump(self) -> None:
        if self.sync_pending:
            self.sync()
        self.popup.poll()
        self.root.after(PUMP_MS, self.pump)

    def locate_codex(self) -> int:
        h = self.codex_hwnd
        if h and win32.is_window(h) and win32.is_visible(h):
            return h
        now = time.monotonic()
        if now - self.last_scan < WINDOW_RESCAN_S and not h:
            return 0
        self.last_scan = now
        windows = win32.find_codex_windows()
        fg = win32.foreground_window()
        self.codex_hwnd = fg if fg in windows else (windows[0] if windows else 0)
        self.codex_pid = win32.window_pid(self.codex_hwnd) if self.codex_hwnd else 0
        if self.codex_hwnd != h or not getattr(self, '_scanned_once', False):
            self._scanned_once = True
            if self.codex_hwnd:
                log.info('Codex window %#x (pid %s, %s) rect=%s', self.codex_hwnd, self.codex_pid,
                         win32.process_path(self.codex_pid), win32.frame_rect(self.codex_hwnd))
            else:
                log.info('no Codex window found (candidates: %s)', windows)
        if not self.codex_hwnd and now - getattr(self, '_described_at', -1e9) > 30:
            self._described_at = now
            for row in win32.describe_windows():
                log.info('  %s', row)
        self.events.watch_process(self.codex_pid or None)
        return self.codex_hwnd

    def sync(self) -> None:
        self.sync_pending = False
        try:
            hwnd = self.locate_codex()
            show = bool(hwnd) and not win32.is_minimized(hwnd) and not win32.is_cloaked(hwnd)
            if not show:
                if self.visible:
                    self.popup.close()
                    self.hide_panel()
                    win32.show_no_activate(self.hwnd, False)
                    self.visible = False
                return
            if self.drag is None:
                self.dock(hwnd)
            if not self.visible:
                win32.show_no_activate(self.hwnd, True)
                self.visible = True
                log.info('strip shown at %s', self.root.geometry())
            extra = (self.panel_hwnd,) if self.panel_visible else ()
            if self.panel_visible:
                self._position_panel()
                win32.place_above(self.panel_hwnd, hwnd, extra=(self.hwnd,))
            win32.place_above(self.hwnd, hwnd, extra=extra)
            self.apply_theme()
        except tk.TclError:
            pass

    def safety_tick(self) -> None:
        self.sync()
        now = time.monotonic()
        if now - getattr(self, '_beat_at', -1e9) > 60:
            self._beat_at = now
            log.info('alive: codex=%#x visible=%s geometry=%s session=%s', self.codex_hwnd or 0, self.visible,
                     self.root.geometry(), Path(self.view.snap.path).name if self.view.snap.path else None)
        self.root.after(SAFETY_TICK_MS, self.safety_tick)

    def dock(self, hwnd: int) -> None:
        rect = win32.frame_rect(hwnd)
        if not rect:
            return
        dpi = win32.dpi_scale(hwnd)
        if abs(dpi - self.dpi) > 0.01:
            self.dpi = dpi
            self._configure_fonts()
            self.rebuild()
            return
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        ox, oy = (round(v * self.dpi) for v in self.offset)
        x = min(max(rect[2] - ox - w, rect[0]), rect[2] - w)
        y = min(max(rect[3] - oy - h, rect[1]), rect[3] - h)
        geo = f'{w}x{h}+{x}+{y}'
        if self.root.geometry() != geo:
            self.root.geometry(geo)

    # ================================================================ lifecycle
    def quit(self) -> None:
        self.events.stop()
        self.watcher.stop()
        self.root.destroy()

    def run(self) -> None:
        pinned = self.settings.get('pinned_thread')
        if pinned:
            self.watcher.pin(pinned)
        self.events.start()
        self.root.after(0, self.data_tick)
        self.root.after(0, self.safety_tick)
        self.root.after(0, self.pump)
        self.root.mainloop()
