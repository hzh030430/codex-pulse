"""Pick the Codex session to show and tail its rollout incrementally."""
from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path

from .metrics import RateWindow, SessionMetrics, Snapshot, parse_ts
from .threads import ThreadIndex, ThreadInfo

INDEX_REFRESH_S = 2.0
SUBAGENT_REFRESH_S = 3.0
QUOTA_REFRESH_S = 10.0
CACHE_SESSIONS = 4
CACHE_SUBAGENTS = 32
QUOTA_TAIL_BYTES = 512 * 1024


def codex_home() -> Path:
    env = os.environ.get('CODEX_HOME')
    return Path(env).expanduser() if env else Path.home() / '.codex'


@dataclass(frozen=True)
class View:
    snap: Snapshot
    thread: ThreadInfo | None = None
    pinned: bool = False


class _Tail:
    """Incremental reader for one rollout file."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.partial = b''
        self.metrics = SessionMetrics(path=str(path))

    def read(self) -> None:
        try:
            size = self.path.stat().st_size
            if size < self.offset:
                self.__init__(self.path)
            if size == self.offset:
                return
            with self.path.open('rb') as fh:
                fh.seek(self.offset)
                chunk = fh.read(size - self.offset)
        except OSError:
            return
        self.offset += len(chunk)
        lines = (self.partial + chunk).split(b'\n')
        self.partial = lines.pop()
        for raw in lines:
            if raw.strip():
                self.metrics.feed(raw.decode('utf-8', errors='replace'))


def latest_rate_limits(path: Path) -> tuple[float, RateWindow | None, RateWindow | None, str | None, str | None] | None:
    """Last ``rate_limits`` in a rollout's tail: (ts, weekly, short, credits, plan)."""
    try:
        size = path.stat().st_size
        with path.open('rb') as fh:
            fh.seek(max(0, size - QUOTA_TAIL_BYTES))
            tail = fh.read().decode('utf-8', errors='replace')
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        if '"rate_limits":{' not in line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        rl = (obj.get('payload') or {}).get('rate_limits')
        if not isinstance(rl, dict):
            continue
        weekly = short = None
        for key in ('primary', 'secondary'):
            win = RateWindow.from_dict(rl.get(key))
            if win is None:
                continue
            if win.is_weekly:
                weekly = win
            else:
                short = win
        credits = rl.get('credits') if isinstance(rl.get('credits'), dict) else {}
        balance = 'unlimited' if credits.get('unlimited') else credits.get('balance')
        return (parse_ts(obj.get('timestamp', '')) or 0.0, weekly, short,
                str(balance) if balance is not None else None, rl.get('plan_type'))
    return None


class SessionWatcher:
    def __init__(self, home: Path | None = None, interval: float = 1.0, price_overrides: dict | None = None):
        self.home = home or codex_home()
        self.index = ThreadIndex(self.home)
        self.interval = interval
        self.price_overrides = price_overrides
        self._lock = threading.Lock()
        self._view = View(Snapshot(error='正在查找 Codex 会话…'))
        self._pinned: str | None = None
        self._tails: OrderedDict[str, _Tail] = OrderedDict()
        self._sub_tails: OrderedDict[str, _Tail] = OrderedDict()
        self._children_for: tuple[str, float, list[ThreadInfo]] = ('', 0.0, [])
        self._auto: ThreadInfo | None = None
        self._auto_at = 0.0
        self._thread_cache: dict[str, ThreadInfo] = {}
        self._quota = None
        self._quota_at = 0.0
        self._recent: list[ThreadInfo] = []
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name='codex-pulse-watcher', daemon=True)

    # ------------------------------------------------------------ public API
    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def view(self) -> View:
        with self._lock:
            return self._view

    def recent_threads(self) -> list[ThreadInfo]:
        with self._lock:
            return list(self._recent)

    def pin(self, thread_id: str | None) -> None:
        with self._lock:
            self._pinned = thread_id
        self._wake.set()

    @property
    def pinned(self) -> str | None:
        with self._lock:
            return self._pinned

    # ------------------------------------------------------------ internals
    def _target(self) -> ThreadInfo | None:
        pinned = self.pinned
        now = time.monotonic()
        if now - self._auto_at > INDEX_REFRESH_S:
            self._auto_at = now
            try:
                recent = self.index.recent(12)
            except Exception:
                recent = []
            with self._lock:
                self._recent = recent
            self._auto = recent[0] if recent else None
            for t in recent:
                self._thread_cache[t.id] = t
        if pinned:
            info = self._thread_cache.get(pinned)
            if info is None:
                try:
                    info = self.index.get(pinned)
                except Exception:
                    info = None
                if info:
                    self._thread_cache[pinned] = info
            return info
        return self._auto

    def _tail(self, path: str, model: str | None = None, pool: OrderedDict[str, _Tail] | None = None,
              cap: int = CACHE_SESSIONS) -> _Tail:
        store = self._tails if pool is None else pool
        tail = store.get(path)
        if tail is None:
            tail = store[path] = _Tail(Path(path))
            while len(store) > cap:
                store.popitem(last=False)
        else:
            store.move_to_end(path)
        tail.metrics.price_overrides = self.price_overrides
        if tail.metrics.model is None and model:
            tail.metrics.model = model
        return tail

    def _subagent_costs(self, thread_id: str) -> tuple[float, float, int, int, int]:
        now = time.monotonic()
        cached_id, cached_at, children = self._children_for
        if cached_id != thread_id or now - cached_at > SUBAGENT_REFRESH_S:
            try:
                children = self.index.spawned_children(thread_id)
            except Exception:
                children = []
            self._children_for = (thread_id, now, children)
        if not children:
            return 0.0, 0.0, 0, 0, 0
        cost = saved = 0.0
        count = fast_n = long_n = 0
        for ch in children:
            if not ch.rollout_path:
                continue
            ct = self._tail(ch.rollout_path, ch.model, self._sub_tails, CACHE_SUBAGENTS)
            ct.read()
            cs = ct.metrics.snapshot()
            mc = cs.main_cost_usd
            ms = cs.main_saved_usd
            if mc is not None:
                cost += mc
            if ms is not None:
                saved += ms
            fast_n += cs.fast_requests
            long_n += cs.long_context_requests
            count += 1
        return cost, saved, count, fast_n, long_n

    def _account_quota(self, snap: Snapshot):
        """Quota is account-wide: prefer the freshest rollout, not just this one."""
        now = time.monotonic()
        if now - self._quota_at > QUOTA_REFRESH_S:
            self._quota_at = now
            newest = self._auto
            if newest is not None and newest.rollout_path != snap.path:
                q = latest_rate_limits(Path(newest.rollout_path))
                if q is not None:
                    self._quota = q
        q = self._quota
        if q and (snap.updated_at is None or q[0] > snap.updated_at):
            ts, weekly, short, credits, plan = q
            return replace(snap, weekly=weekly or snap.weekly, short=short or snap.short,
                           credits=credits or snap.credits, plan=plan or snap.plan)
        return snap

    def poll_once(self) -> View:
        info = self._target()
        if info is None or not info.rollout_path:
            view = View(Snapshot(error='未找到 Codex 会话记录'), None, bool(self.pinned))
        else:
            tail = self._tail(info.rollout_path, info.model)
            tail.read()
            sub_cost, sub_saved, sub_n, sub_fast, sub_long = self._subagent_costs(info.id)
            snap = tail.metrics.snapshot()
            if sub_n:
                snap = replace(
                    snap,
                    subagent_cost_usd=sub_cost,
                    subagent_saved_usd=sub_saved,
                    subagent_count=sub_n,
                    fast_requests=snap.fast_requests + sub_fast,
                    long_context_requests=snap.long_context_requests + sub_long,
                )
            snap = self._account_quota(snap)
            view = View(snap, info, bool(self.pinned))
        with self._lock:
            self._view = view
        return view

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                with self._lock:
                    self._view = View(Snapshot(error=f'读取失败：{exc.__class__.__name__}: {exc}'))
            self._wake.wait(self.interval)
            self._wake.clear()
