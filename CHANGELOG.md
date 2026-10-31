# Changelog

All notable changes to **Codex Pulse** will be documented in this file.

## [1.0.0] - 2026-10-31

### Added
- **Non-Intrusive Docked Status Strip**: Attaches cleanly to the bottom-right inside edge of the OpenAI Codex Desktop window on Windows 10/11 using WinEvent hooks and z-order tracking (stays visible whenever Codex is visible regardless of focus, hides automatically when Codex is minimized or covered by another window, and never steals keyboard focus).
- **6 Live Status Strip Metrics**: Context window usage (`%` + color-coded bar), Session Tokens, API-equivalent Session Cost (`$`), Prompt Cache Hit Rate (`%`), Session Throughput (`TPS`), and Weekly Quota (`%` + bar).
- **Hover / Click-to-Pin Detail Dashboard**: 5 KPI summary cards plus 7 structured detail sections (Session, Context, Current Turn, Cost, Tokens, Speed, Quota).
- **Accurate Per-Request Official OpenAI API Cost Engine**:
  - Covers all current Codex Desktop picker models (`GPT-6.1 Sol`, `GPT-6 Astra`, `GPT-6.1 Terra`, `GPT-6 Sol`, `GPT-6 Luna`, `GPT-5.6 Sol`, `GPT-5.6 Terra`, `GPT-5.6 Luna` + internal aliases `gpt-reserve`, `codex-auto-review`) and historical GPT-5 / o-series / GPT-4.1 Codex models.
  - Per-request tracking handles mid-session model switches, prompt cache discounts (90%–95%), **Long-Context (`>272K` input tokens: `2×` input/cached, `1.5×` output)**, and **Fast / Priority mode (`2×`, stackable with `>272K`)**.
  - Recursive aggregation of spawned subagent thread costs via `state_5.sqlite` (`thread_spawn_edges`).
- **Fluent Custom Right-Click Menu**:
  - Session switcher (Auto-follow most recent active session or pin any specific session).
  - Theme selector (`System` / `Light` / `Dark`) & instant `中文` / `English` language toggle.
  - Smooth anti-aliased linear sliders for **Size** (`S`–`L`, `75%`–`125%` on top of per-monitor DPI) and **Opacity** (`0%`–`100%`, with click-through protection at `0%`).
- **Zero External Dependencies**: Pure Python 3.10+ standard library (`tkinter`, `ctypes`, `sqlite3`), 100% local read-only access to `~/.codex` with zero network requests and zero credential access.
