"""Entry point: ``pythonw -m codex_pulse`` (or ``python -m codex_pulse --once``)."""
from __future__ import annotations

import argparse
import sys

from .metrics import duration, human
from .pricing import fmt_rate, fmt_usd, is_fast_tier


def print_once() -> int:
    from .overlay import load_settings
    from .watcher import SessionWatcher
    settings = load_settings()
    overrides = settings.get('pricing') if isinstance(settings.get('pricing'), dict) else None
    view = SessionWatcher(price_overrides=overrides).poll_once()
    s, th = view.snap, view.thread
    if s.error and not s.totals:
        print(s.error)
        return 1
    t = s.totals
    tier_tag = ' · Fast' if is_fast_tier(s.service_tier) else ''
    print(f'thread  : {th.title if th else "?"}  [{th.project if th else "?"} · {th.git_branch if th else "?"}]')
    print(f'file    : {s.path}')
    print(f'model   : {s.model} · {s.effort}{tier_tag}   perms: {s.approval} / {s.sandbox}')
    if s.context_ratio is not None:
        print(f'context : {human(s.context_used)} / {human(s.context_window)} ({s.context_ratio * 100:.1f}%), '
              f'compactions {s.compactions}')
    if t:
        print(f'tokens  : {human(t.total_tokens)}  in {t.input_tokens:,}  cached {t.cached_input_tokens:,}  '
              f'out {t.output_tokens:,}  reasoning {t.reasoning_output_tokens:,}')
        print(f'cache   : {t.cache_rate * 100:.2f}%' if t.cache_rate is not None else 'cache   : —')
    if s.total_cost_usd is not None:
        sub_note = f' (main {fmt_usd(s.main_cost_usd)} + {s.subagent_count} subagents {fmt_usd(s.subagent_cost_usd)})' if s.subagent_count else ''
        saved_note = f', cache saved {fmt_usd(s.total_saved_usd)}' if s.total_saved_usd else ''
        mults = []
        if s.fast_requests:
            mults.append(f'Fast×{s.fast_requests}')
        if s.long_context_requests:
            mults.append(f'>272K×{s.long_context_requests}')
        mult_note = f' ({", ".join(mults)})' if mults else ''
        rate_str = fmt_rate(s.model, s.service_tier, s.last_input_tokens, overrides=overrides)
        print(f'cost    : {fmt_usd(s.total_cost_usd)}{sub_note}{saved_note}{mult_note}  [{rate_str}]')
    if s.session_tps:
        print(f'tps     : {s.session_tps:.1f} over {s.samples} requests; last {s.last_tps:.1f}')
    if s.avg_ttft_ms:
        print(f'ttft    : {s.avg_ttft_ms / 1000:.1f}s avg; turn {duration((s.avg_turn_ms or 0) / 1000)} avg; turns {s.turns}')
    if s.weekly:
        print(f'weekly  : {s.weekly.used_percent:.0f}% used, resets_at {s.weekly.resets_at}')
    if s.short:
        print(f'5h      : {s.short.used_percent:.0f}% used')
    print(f'credits : {s.credits}  plan: {s.plan}')
    print(f'active  : {s.active}  turn tools: {s.turn_tool_calls}')
    return 0


def log_path():
    import os
    from pathlib import Path
    p = Path(os.environ.get('APPDATA', Path.home())) / 'CodexPulse' / 'codex-pulse.log'
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def setup_logging():
    """pythonw has no console: send errors (and hard crashes) to a log file."""
    import faulthandler
    import logging
    path = log_path()
    if path.exists() and path.stat().st_size > 1_000_000:
        path.unlink()
    logging.basicConfig(filename=path, level=logging.INFO, encoding='utf-8',
                        format='%(asctime)s %(levelname)s %(message)s')
    crash = open(path, 'a', encoding='utf-8')
    faulthandler.enable(crash)
    sys.excepthook = lambda t, e, tb: logging.critical('uncaught', exc_info=(t, e, tb))
    return logging.getLogger('codex_pulse')


def main(argv: list[str] | None = None) -> int:
    from . import __version__
    parser = argparse.ArgumentParser(prog='codex_pulse', description='Codex Desktop 会话状态条 / Status Overlay')
    parser.add_argument('-V', '--version', action='version', version=f'codex-pulse {__version__}')
    parser.add_argument('--once', action='store_true', help='只打印一次当前会话统计，不显示悬浮条')
    args = parser.parse_args(argv)
    if args.once:
        return print_once()

    log = setup_logging()
    from . import win32
    win32.enable_dpi_awareness()
    if not win32.single_instance():
        log.info('already running; exiting')
        from .i18n import I18n, system_lang
        from .overlay import load_settings
        i18n = I18n(load_settings().get('lang') or system_lang())
        win32.message_box(i18n.t('msg.running'), 'Codex Pulse')
        return 0
    log.info('starting')
    from .overlay import Overlay, load_settings
    from .watcher import SessionWatcher
    settings = load_settings()
    overrides = settings.get('pricing') if isinstance(settings.get('pricing'), dict) else None
    watcher = SessionWatcher(price_overrides=overrides)
    watcher.start()
    Overlay(watcher).run()
    log.info('exited normally')
    return 0


if __name__ == '__main__':
    sys.exit(main())
