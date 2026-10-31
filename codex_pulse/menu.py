"""Custom-drawn context menu (themed, rounded, with inline segmented controls & linear sliders)."""
from __future__ import annotations

import ctypes
import math
import struct
import tkinter as tk
import tkinter.font as tkfont
import zlib

from . import win32

VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04
_GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState


def _mouse_down() -> bool:
    return any(_GetAsyncKeyState(vk) & 0x8000 for vk in (VK_LBUTTON, VK_RBUTTON, VK_MBUTTON))


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload) & 0xFFFFFFFF)


def _thumb_png(diam: int, outer_hex: str, inner_hex: str, inner_ratio: float) -> bytes:
    """4x-supersampled RGBA PNG of a Fluent-style circular slider thumb."""
    or_, og, ob = _rgb(outer_hex)
    ir, ig, ib = _rgb(inner_hex)
    half = diam / 2.0
    ro = half - 0.6
    ri = ro * inner_ratio
    ro2, ri2 = ro * ro, ri * ri
    rows = bytearray()
    offsets = (0.125, 0.375, 0.625, 0.875)
    for py in range(diam):
        rows.append(0)
        for px in range(diam):
            sr = sg = sb = hits = 0
            for oy in offsets:
                dy2 = (py + oy - half) ** 2
                for ox in offsets:
                    d2 = (px + ox - half) ** 2 + dy2
                    if d2 <= ri2:
                        sr += ir; sg += ig; sb += ib; hits += 1
                    elif d2 <= ro2:
                        sr += or_; sg += og; sb += ob; hits += 1
            if hits:
                rows.extend((sr // hits, sg // hits, sb // hits, (hits * 255 + 8) // 16))
            else:
                rows.extend((0, 0, 0, 0))
    ihdr = struct.pack('>IIBBBBB', diam, diam, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + _png_chunk(b'IHDR', ihdr) + _png_chunk(b'IDAT', zlib.compress(bytes(rows))) + _png_chunk(b'IEND', b'')


class PopupMenu:
    """Main menu + a session flyout, both borderless Toplevels styled like the panel."""

    def __init__(self, ov):
        self.ov = ov
        self.dpi = 1.0
        self.win = self._toplevel()
        self.fly = self._toplevel()
        self.open = False
        self.fly_open = False
        self.armed = False
        self.press_inside = False
        self.anchor = (0, 0)
        self.themed: list = []
        self.redraws: list = []
        self._thumbs: dict[tuple, tk.PhotoImage] = {}
        self.fonts = {name: tkfont.Font(root=ov.root) for name in ('body', 'head', 'sub', 'seg', 'val')}
        self._configure_fonts()

    # ------------------------------------------------------------ plumbing
    def px(self, v: float) -> int:
        return max(1, round(v * self.dpi))

    def _configure_fonts(self) -> None:
        zh = self.ov.i18n.lang == 'zh'
        text = 'Microsoft YaHei UI' if zh else 'Segoe UI'
        num = 'Segoe UI Semibold'
        spec = {
            'body': (text, 12, 'normal'), 'head': (text, 11, 'bold'),
            'sub': (text, 11, 'normal'), 'seg': (text, 11, 'normal'), 'val': (num, 11, 'normal'),
        }
        for name, (family, size, weight) in spec.items():
            self.fonts[name].configure(family=family, size=-max(9, round(size * self.dpi)), weight=weight)

    def _thumb(self, diam: int, outer_hex: str, inner_hex: str, inner_ratio: float) -> tk.PhotoImage:
        key = (diam, outer_hex, inner_hex, round(inner_ratio, 2))
        img = self._thumbs.get(key)
        if img is None:
            img = tk.PhotoImage(master=self.ov.root, data=_thumb_png(*key))
            self._thumbs[key] = img
        return img

    def _toplevel(self) -> tk.Toplevel:
        w = tk.Toplevel(self.ov.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        return w

    def _hwnd(self, win: tk.Toplevel) -> int:
        return win32.root_window(int(win.winfo_id()))

    def _style(self, win: tk.Toplevel) -> None:
        win.deiconify()
        win.update_idletasks()
        hwnd = self._hwnd(win)
        win32.style_overlay(hwnd)
        if self.ov.win11:
            win32.set_border_color(hwnd, self.ov.pal['border'])

    def W(self, cls, parent, roles, **kw):
        w = cls(parent, **kw)
        self.themed.append((w, roles))
        return w

    def L(self, parent, text, font='body', fg='text', bg='bg', **kw):
        return self.W(tk.Label, parent, {'bg': bg, 'fg': fg}, text=text, font=self.fonts[font],
                      bd=0, padx=0, pady=0, **kw)

    def F(self, parent, bg='bg', **kw):
        return self.W(tk.Frame, parent, {'bg': bg}, bd=0, **kw)

    def _theme(self) -> None:
        pal = self.ov.pal
        for w, roles in self.themed:
            try:
                w.configure(**{opt: pal[role] for opt, role in roles.items()})
            except tk.TclError:
                pass
        for fn in self.redraws:
            try:
                fn()
            except tk.TclError:
                pass

    def _container(self, win: tk.Toplevel) -> tk.Frame:
        for child in win.winfo_children():
            child.destroy()
        border = 0 if self.ov.win11 else 1
        outer = self.W(tk.Frame, win, {'bg': 'bg', 'highlightbackground': 'border', 'highlightcolor': 'border'},
                       bd=0, highlightthickness=border)
        outer.pack(fill='both', expand=True)
        body = self.F(outer)
        body.pack(fill='both', expand=True, padx=self.px(6), pady=self.px(6))
        return body

    def _row(self, parent, on_click=None, on_hover=None) -> tuple[tk.Frame, tk.Frame]:
        """A full-width hoverable row; returns (row, inner)."""
        P = self.px
        row = self.F(parent)
        row.pack(fill='x')
        inner = self.F(row)
        inner.pack(fill='x', padx=P(10), pady=P(6))

        def widgets():
            out, stack = [row], [inner]
            while stack:
                w = stack.pop()
                if getattr(w, '_seg', False) or w.winfo_class() not in ('Label', 'Frame'):
                    continue
                out.append(w)
                stack.extend(w.winfo_children())
            return out

        def enter(_e):
            for w in widgets():
                w.configure(bg=self.ov.pal['hover'])
            if on_hover:
                on_hover()

        def leave(_e):
            for w in widgets():
                w.configure(bg=self.ov.pal['bg'])

        if on_click or on_hover:
            for w in (row, inner):
                w.bind('<Enter>', enter)
                w.bind('<Leave>', leave)
                if on_click:
                    w.bind('<ButtonRelease-1>', lambda _e: on_click())
            row._enter, row._leave = enter, leave
        return row, inner

    def _bind_children(self, row: tk.Frame, on_click=None) -> None:
        for w in row.winfo_children()[0].winfo_children() if row.winfo_children() else []:
            if getattr(w, '_seg', False):
                continue
            if hasattr(row, '_enter'):
                w.bind('<Enter>', row._enter)
                w.bind('<Leave>', row._leave)
            if on_click:
                w.bind('<ButtonRelease-1>', lambda _e: on_click())

    def _sep(self, parent) -> None:
        P = self.px
        self.F(parent, bg='sep', height=1).pack(fill='x', padx=P(10), pady=P(4))

    def _segmented(self, parent, options, current, command) -> tk.Frame:
        P = self.px
        box = self.F(parent, bg='seg')
        box._seg = True
        inner = self.F(box, bg='seg')
        inner._seg = True
        inner.pack(padx=P(2), pady=P(2))
        for value, label in options:
            on = value == current
            roles = {'bg': 'seg_on' if on else 'seg', 'fg': 'seg_text_on' if on else 'muted'}
            item = self.W(tk.Label, inner, roles, text=label, font=self.fonts['seg'], bd=0,
                          padx=P(8), pady=P(2), cursor='hand2')
            item._seg = True
            item.pack(side='left')
            item.bind('<ButtonRelease-1>', lambda _e, v=value: self._choose(command, v))
        return box

    def _slider(self, parent, value: float, min_v: float, max_v: float, fmt, on_change,
                ends: tuple[str, str] | None = None, snap: float | None = None, snap_tol: float = 0.0) -> tk.Canvas:
        """Smooth linear slider with optional end-cap labels (S/L), center tick, and live readout."""
        P = self.px
        w, h = P(186), P(24)
        cy = h // 2
        diam = max(14, P(15))
        diam += diam % 2
        rad = diam // 2
        track_h = max(3, P(4))
        slider_right = w - P(42)
        if ends:
            x0, x1 = P(15) + rad, slider_right - P(15) - rad
        else:
            x0, x1 = rad, slider_right - rad

        c = self.W(tk.Canvas, parent, {'bg': 'bg'}, width=w, height=h, bd=0, highlightthickness=0, cursor='hand2')
        c._seg = True
        state = {'v': float(value), 'drag': False, 'hover': False}

        def pos_x(v: float) -> int:
            t = max(0.0, min(1.0, (v - min_v) / (max_v - min_v)))
            return round(x0 + t * (x1 - x0))

        def val_at(ex: int) -> float:
            t = max(0.0, min(1.0, (ex - x0) / max(1, x1 - x0)))
            v = min_v + t * (max_v - min_v)
            if snap is not None and 0.02 < t < 0.98 and abs(v - snap) <= snap_tol:
                v = snap
            return v

        def draw() -> None:
            pal = getattr(self.ov, 'pal', None)
            if not pal:
                return
            c.delete('all')
            if ends:
                c.create_text(P(6), cy, text=ends[0], font=self.fonts['val'], fill=pal['faint'])
                c.create_text(slider_right - P(6), cy, text=ends[1], font=self.fonts['val'], fill=pal['faint'])
            if snap is not None:
                sx = pos_x(snap)
                c.create_line(sx, cy - P(5), sx, cy + P(5), fill=pal['border'], width=max(1, P(1)))
            c.create_line(x0, cy, x1, cy, fill=pal['track'], width=track_h, capstyle='round')
            cx = pos_x(state['v'])
            if cx > x0:
                c.create_line(x0, cy, cx, cy, fill=pal['accent'], width=track_h, capstyle='round')
            active = state['drag'] or state['hover']
            img = self._thumb(diam, pal['accent'], '#ffffff', 0.56 if active else 0.42)
            c.create_image(cx, cy, image=img)
            c.create_text(w, cy, text=fmt(state['v']), anchor='e', font=self.fonts['val'],
                          fill=pal['accent'] if state['drag'] else pal['text'])

        def on_enter(_e) -> None:
            state['hover'] = True
            self._close_fly()
            draw()

        def on_leave(_e) -> None:
            state['hover'] = False
            draw()

        def on_press(e) -> None:
            self.press_inside = True
            state['drag'] = True
            state['v'] = val_at(e.x)
            draw()
            on_change(state['v'], save=False)

        def on_motion(e) -> None:
            if not state['drag']:
                return
            state['v'] = val_at(e.x)
            draw()
            on_change(state['v'], save=False)

        def on_release(e) -> None:
            if not state['drag']:
                return
            state['drag'] = False
            state['v'] = val_at(e.x)
            draw()
            on_change(state['v'], save=True)

        c.bind('<Enter>', on_enter)
        c.bind('<Leave>', on_leave)
        c.bind('<ButtonPress-1>', on_press)
        c.bind('<B1-Motion>', on_motion)
        c.bind('<ButtonRelease-1>', on_release)
        self.redraws.append(draw)
        draw()
        return c

    def _choose(self, command, value) -> None:
        command(value)
        if self.open:  # settings may have rebuilt language / palette: redraw in place
            self.show(*self.anchor)

    # ------------------------------------------------------------ content
    def _build_main(self) -> None:
        ov, t = self.ov, self.ov.t
        P = self.px
        self.themed = [x for x in self.themed if x[0].winfo_toplevel() is self.fly]
        self.redraws = []
        body = self._container(self.win)

        head = self.F(body)
        head.pack(fill='x', padx=P(10), pady=(P(4), P(6)))
        self.L(head, 'Codex Pulse', font='head', fg='faint').pack(side='left')

        # session row with flyout
        pinned = ov.watcher.pinned
        current = t('val.auto')
        if pinned:
            th = next((x for x in ov.watcher.recent_threads() if x.id == pinned), None)
            current = th.title if th else t('val.pinned')
        if len(current) > 16:
            current = current[:15] + '…'
        row, inner = self._row(body, on_hover=self._open_fly)
        self.session_row = row
        self.L(inner, t('menu.session'), anchor='w').pack(side='left')
        self.L(inner, '›', fg='faint').pack(side='right')
        self.L(inner, current, fg='muted').pack(side='right', padx=(P(16), P(8)))
        self._bind_children(row)
        self._sep(body)

        # inline settings: segmented switches (theme, language) + linear sliders (size, opacity)
        grid = self.F(body)
        grid.pack(fill='x', padx=P(10), pady=P(2))
        grid.grid_columnconfigure(1, weight=1)

        seg_rows = [
            ('foot.theme', [(k, t(f'theme.{k}')) for k in ('system', 'light', 'dark')], ov.theme_pref, ov.set_theme),
            ('foot.lang', [('zh', '中文'), ('en', 'EN')], ov.i18n.lang, ov.set_lang),
        ]
        for r, (label, options, value, command) in enumerate(seg_rows):
            lab = self.L(grid, t(label), fg='muted', anchor='w')
            lab.grid(row=r, column=0, sticky='w', pady=P(3))
            seg = self._segmented(grid, options, value, command)
            seg.grid(row=r, column=1, sticky='e', padx=(P(18), 0), pady=P(3))
            for w in (lab, seg):
                w.bind('<Enter>', lambda _e: self._close_fly(), add='+')

        size_lab = self.L(grid, t('menu.size'), fg='muted', anchor='w')
        size_lab.grid(row=2, column=0, sticky='w', pady=P(3))
        size_sl = self._slider(grid, ov.size_scale, ov.SIZE_MIN, ov.SIZE_MAX,
                               lambda v: f'{round(v * 100)}%', ov.set_size,
                               ends=('S', 'L'), snap=1.0, snap_tol=0.015)
        size_sl.grid(row=2, column=1, sticky='e', padx=(P(18), 0), pady=P(3))

        opa_lab = self.L(grid, t('menu.opacity'), fg='muted', anchor='w')
        opa_lab.grid(row=3, column=0, sticky='w', pady=P(3))
        opa_sl = self._slider(grid, ov.opacity, 0, 100,
                              lambda v: f'{round(v)}%', ov.set_opacity)
        opa_sl.grid(row=3, column=1, sticky='e', padx=(P(18), 0), pady=P(3))

        for w in (grid, size_lab, opa_lab):
            w.bind('<Enter>', lambda _e: self._close_fly(), add='+')
        self._sep(body)

        for label, action in (('menu.reveal', ov.reveal_session), ('menu.reset', ov.reset_position)):
            row, inner = self._row(body, on_click=lambda a=action: self._act(a), on_hover=self._close_fly)
            self.L(inner, t(label), anchor='w').pack(side='left')
            self._bind_children(row, lambda a=action: self._act(a))
        self._sep(body)
        row, inner = self._row(body, on_click=lambda: self._act(ov.quit), on_hover=self._close_fly)
        self.L(inner, t('menu.quit'), fg='bad', anchor='w').pack(side='left')
        self._bind_children(row, lambda: self._act(ov.quit))

    def _build_fly(self) -> None:
        ov, t, i = self.ov, self.ov.t, self.ov.i18n
        P = self.px
        self.themed = [x for x in self.themed if x[0].winfo_toplevel() is self.win]
        body = self._container(self.fly)
        pinned = ov.watcher.pinned

        def entry(title, subtitle, selected, tid):
            row, inner = self._row(body, on_click=lambda: self._pick(tid))
            mark = self.L(inner, '✓' if selected else '', fg='accent', width=2, anchor='w')
            mark.pack(side='left', anchor='n')
            text = self.F(inner)
            text.pack(side='left', fill='x')
            self.L(text, title, anchor='w').pack(fill='x')
            if subtitle:
                self.L(text, subtitle, font='sub', fg='faint', anchor='w').pack(fill='x')
            for w in (mark, text, *text.winfo_children()):
                w.bind('<Enter>', row._enter)
                w.bind('<Leave>', row._leave)
                w.bind('<ButtonRelease-1>', lambda _e: self._pick(tid))

        entry(t('menu.auto'), None, not pinned, None)
        self._sep(body)
        threads = ov.watcher.recent_threads()
        if not threads:
            self.L(body, t('menu.none'), fg='faint').pack(padx=P(10), pady=P(6))
        for th in threads[:10]:
            title = th.title if len(th.title) <= 34 else th.title[:33] + '…'
            when = i.ago(th.updated_at_ms / 1000) if th.updated_at_ms else ''
            entry(title, '  ·  '.join(x for x in (th.project, when) if x), th.id == pinned, th.id)

    # ------------------------------------------------------------ actions
    def _act(self, action) -> None:
        self.close()
        action()

    def _pick(self, thread_id) -> None:
        self.close()
        self.ov.choose_session(thread_id)

    def _open_fly(self) -> None:
        if self.fly_open:
            return
        self._build_fly()
        self._theme()
        self.fly.update_idletasks()
        fw, fh = self.fly.winfo_reqwidth(), self.fly.winfo_reqheight()
        row = self.session_row
        mx, my = self.win.winfo_rootx(), row.winfo_rooty()
        mw = self.win.winfo_width()
        left, top, right, bottom = win32.work_area(mx, my)
        x = mx + mw + self.px(4)
        if x + fw > right:
            x = mx - fw - self.px(4)
        y = min(max(top, my - self.px(6)), bottom - fh)
        self.fly.geometry(f'{fw}x{fh}+{max(left, x)}+{y}')
        self._style(self.fly)
        self.fly_open = True

    def _close_fly(self) -> None:
        if self.fly_open:
            self.fly.withdraw()
            self.fly_open = False

    # ------------------------------------------------------------ open / close
    def show(self, x: int, y: int) -> None:
        self.anchor = (x, y)
        self.dpi = self.ov.dpi
        self._configure_fonts()
        was_fly = self.fly_open
        self._close_fly()
        self._build_main()
        self._theme()
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        left, top, right, bottom = win32.work_area(x, y)
        px = min(max(left, x), right - w)
        py = y - h if y + h > bottom else y
        self.win.geometry(f'{w}x{h}+{px}+{max(top, py)}')
        self._style(self.win)
        self.armed = not _mouse_down()
        self.press_inside = False
        self.open = True
        if was_fly:
            self._open_fly()

    def close(self) -> None:
        self._close_fly()
        self.press_inside = False
        if self.open:
            self.win.withdraw()
            self.open = False

    def _inside(self, win: tk.Toplevel) -> bool:
        px, py = self.ov.root.winfo_pointerxy()
        x, y = win.winfo_rootx(), win.winfo_rooty()
        return x <= px < x + win.winfo_width() and y <= py < y + win.winfo_height()

    def poll(self) -> None:
        """Close on a click starting outside (the menu never takes focus, so no FocusOut)."""
        if not self.open:
            return
        down = _mouse_down()
        if not down:
            self.armed = True
            self.press_inside = False
            return
        if not self.armed or self.press_inside:
            return
        if self._inside(self.win) or (self.fly_open and self._inside(self.fly)):
            self.press_inside = True
            return
        self.close()
