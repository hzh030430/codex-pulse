"""Build release artifacts into dist/ (pure Python 3.10+ stdlib, zero external build deps).

Outputs:
  - dist/CodexPulse-v<version>-windows-portable.zip
  - dist/codex-pulse-<version>.pyz
  - dist/codex_pulse-<version>-py3-none-any.whl
  - dist/codex_pulse-<version>.tar.gz
  - dist/SHA256SUMS.txt
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import shutil
import sys
import tarfile
import tempfile
import zipapp
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from codex_pulse import __version__ as VERSION  # noqa: E402

DIST = ROOT / 'dist'

PORTABLE_FILES = [
    'Start Codex Pulse.vbs',
    'install.ps1',
    'uninstall.ps1',
    'start.ps1',
    'create-desktop-shortcut.ps1',
    'install-autostart.ps1',
    'README.md',
    'README.en.md',
    'CHANGELOG.md',
    'LICENSE',
    'assets/codex-pulse.ico',
]

SDIST_EXTRA = [
    'pyproject.toml',
    'tests/test_metrics.py',
    'tools/build_release.py',
    'tools/make_icon.py',
    'tools/diagnose-codex-window.ps1',
    'tools/diagnose.cmd',
]


def _iter_pkg_files() -> list[Path]:
    out: list[Path] = []
    for p in sorted((ROOT / 'codex_pulse').rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith(('.pyc', '.pyo')):
            out.append(p)
    return out


def build_portable_zip() -> Path:
    target = DIST / f'CodexPulse-v{VERSION}-windows-portable.zip'
    prefix = 'CodexPulse'
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in PORTABLE_FILES:
            zf.write(ROOT / rel, f'{prefix}/{rel}')
        for p in _iter_pkg_files():
            zf.write(p, f"{prefix}/{p.relative_to(ROOT).as_posix()}")
    return target


def build_pyz() -> Path:
    target = DIST / f'codex-pulse-{VERSION}.pyz'
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / 'app'
        stage.mkdir()
        for p in _iter_pkg_files():
            dest = stage / p.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        zipapp.create_archive(stage, target, main='codex_pulse.__main__:main', compressed=True)
    return target


def _b64_sha256(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return 'sha256=' + base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def build_wheel() -> Path:
    dist_info = f'codex_pulse-{VERSION}.dist-info'
    target = DIST / f'codex_pulse-{VERSION}-py3-none-any.whl'
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    metadata = (
        'Metadata-Version: 2.1\n'
        'Name: codex-pulse\n'
        f'Version: {VERSION}\n'
        'Summary: Non-intrusive floating status bar and real-time token, cache, TPS, API cost, and quota dashboard docked to OpenAI Codex Desktop on Windows.\n'
        'Home-page: https://github.com/hzh030430/codex-pulse\n'
        'Author: hzh030430\n'
        'License: MIT\n'
        'Requires-Python: >=3.10\n'
        'Description-Content-Type: text/markdown\n\n'
        + readme
    ).encode('utf-8')
    wheel_meta = (
        'Wheel-Version: 1.0\n'
        'Generator: codex-pulse-build\n'
        'Root-Is-Purelib: true\n'
        'Tag: py3-none-any\n'
    ).encode('utf-8')
    entry_points = (
        '[console_scripts]\n'
        'codex-pulse-cli = codex_pulse.__main__:main\n\n'
        '[gui_scripts]\n'
        'codex-pulse = codex_pulse.__main__:main\n'
    ).encode('utf-8')
    license_bytes = (ROOT / 'LICENSE').read_bytes()

    records: list[tuple[str, str, str]] = []
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in _iter_pkg_files():
            arc = p.relative_to(ROOT).as_posix()
            data = p.read_bytes()
            zf.writestr(arc, data)
            records.append((arc, _b64_sha256(data), str(len(data))))
        for name, blob in (
            ('METADATA', metadata),
            ('WHEEL', wheel_meta),
            ('entry_points.txt', entry_points),
            ('LICENSE', license_bytes),
        ):
            arc = f'{dist_info}/{name}'
            zf.writestr(arc, blob)
            records.append((arc, _b64_sha256(blob), str(len(blob))))
        rec_arc = f'{dist_info}/RECORD'
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator='\n')
        for row in records:
            writer.writerow(row)
        writer.writerow((rec_arc, '', ''))
        zf.writestr(rec_arc, buf.getvalue().encode('utf-8'))
    return target


def build_sdist() -> Path:
    base = f'codex_pulse-{VERSION}'
    target = DIST / f'{base}.tar.gz'
    rels = list(dict.fromkeys(PORTABLE_FILES + SDIST_EXTRA))
    with tarfile.open(target, 'w:gz') as tf:
        for rel in rels:
            src = ROOT / rel
            if src.exists():
                tf.add(src, arcname=f'{base}/{rel}')
        for p in _iter_pkg_files():
            tf.add(p, arcname=f'{base}/{p.relative_to(ROOT).as_posix()}')
    return target


def write_checksums(files: list[Path]) -> Path:
    out = DIST / 'SHA256SUMS.txt'
    lines = []
    for f in files:
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        lines.append(f'{h}  {f.name}')
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return out


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    artifacts = [
        build_portable_zip(),
        build_pyz(),
        build_wheel(),
        build_sdist(),
    ]
    sums = write_checksums(artifacts)
    for p in [*artifacts, sums]:
        print(f'{p.name:44}  {p.stat().st_size:>9,} bytes')


if __name__ == '__main__':
    main()
