"""Read-only access to Codex's thread index (``state_5.sqlite`` -> ``threads``)."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ThreadInfo:
    id: str
    title: str
    rollout_path: str
    cwd: str | None
    git_branch: str | None
    model: str | None
    effort: str | None
    approval: str | None
    updated_at_ms: int | None

    @property
    def project(self) -> str | None:
        return Path(self.cwd).name if self.cwd else None


def clean_title(raw: str | None, limit: int = 60) -> str:
    if not raw:
        return '(未命名会话)'
    text = re.sub(r'[*_`#>]+', '', raw)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), '')
    first = re.sub(r'\s+', ' ', first)
    return first if len(first) <= limit else first[:limit - 1] + '…'


def _db_path(codex_home: Path) -> Path | None:
    candidates = sorted(codex_home.glob('state_*.sqlite'),
                        key=lambda p: int(re.sub(r'\D', '', p.stem) or 0), reverse=True)
    return candidates[0] if candidates else None


class ThreadIndex:
    def __init__(self, codex_home: Path):
        self.codex_home = codex_home

    def _query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        db = _db_path(self.codex_home)
        if db is None:
            return []
        con = sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True, timeout=1.0)
        try:
            con.row_factory = sqlite3.Row
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    _COLUMNS = ('id, title, rollout_path, cwd, git_branch, model, reasoning_effort, '
                'approval_mode, updated_at_ms')

    @staticmethod
    def _info(row: sqlite3.Row) -> ThreadInfo:
        path = row['rollout_path'] or ''
        if path.startswith('\\\\?\\'):  # extended-length prefix confuses Explorer
            path = path[4:]
        return ThreadInfo(row['id'], clean_title(row['title']), path, row['cwd'],
                          row['git_branch'], row['model'], row['reasoning_effort'],
                          row['approval_mode'], row['updated_at_ms'])

    def recent(self, limit: int = 12) -> list[ThreadInfo]:
        """User-facing threads (no subagents / guardian reviews), newest first."""
        rows = self._query(
            f'SELECT {self._COLUMNS} FROM threads '
            "WHERE archived = 0 AND (thread_source IS NULL OR thread_source = 'user') "
            'AND rollout_path IS NOT NULL ORDER BY updated_at_ms DESC LIMIT ?', (limit,))
        return [self._info(r) for r in rows]

    def get(self, thread_id: str) -> ThreadInfo | None:
        rows = self._query(f'SELECT {self._COLUMNS} FROM threads WHERE id = ?', (thread_id,))
        return self._info(rows[0]) if rows else None

    def by_rollout(self, path: str) -> ThreadInfo | None:
        rows = self._query(f'SELECT {self._COLUMNS} FROM threads WHERE rollout_path = ?', (path,))
        return self._info(rows[0]) if rows else None

    def spawned_children(self, thread_id: str) -> list[ThreadInfo]:
        """All descendant subagent / attached threads spawned by ``thread_id``."""
        try:
            rows = self._query(
                'WITH RECURSIVE tree(id) AS ('
                '  SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id = ? '
                '  UNION SELECT id FROM threads WHERE attached_thread_parent_id = ? '
                '  UNION SELECT e.child_thread_id FROM thread_spawn_edges e JOIN tree ON e.parent_thread_id = tree.id '
                '  UNION SELECT t.id FROM threads t JOIN tree ON t.attached_thread_parent_id = tree.id'
                f') SELECT {self._COLUMNS} FROM threads '
                'WHERE id IN tree AND id != ? AND rollout_path IS NOT NULL',
                (thread_id, thread_id, thread_id),
            )
            return [self._info(r) for r in rows]
        except sqlite3.OperationalError:
            return []
