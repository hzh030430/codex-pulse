"""Generate assets/codex-pulse.ico (pure stdlib: PNG frames inside an ICO)."""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

BG = (30, 30, 32)
BORDER = (72, 72, 76)
LINE = (74, 222, 128)
# Pulse polyline in unit coordinates (x, y), y grows downward.
PULSE = [(0.14, 0.56), (0.34, 0.56), (0.42, 0.40), (0.50, 0.74), (0.60, 0.26), (0.68, 0.56), (0.86, 0.56)]


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _rounded_alpha(x, y, size, radius):
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    d = math.hypot(x - cx, y - cy)
    return max(0.0, min(1.0, radius - d + 0.5))


def render(size: int) -> bytes:
    radius, stroke, ss = size * 0.22, max(1.6, size * 0.075), 4
    pts = [(x * size, y * size) for x, y in PULSE]
    rows = []
    for j in range(size):
        row = bytearray(b'\x00')  # PNG filter: none
        for i in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sj in range(ss):
                for si in range(ss):
                    x, y = i + (si + 0.5) / ss, j + (sj + 0.5) / ss
                    a = _rounded_alpha(x, y, size, radius)
                    if a <= 0:
                        continue
                    edge = _rounded_alpha(x, y, size, radius) - _rounded_alpha(
                        min(max(x, 1.2), size - 1.2), min(max(y, 1.2), size - 1.2), size, radius - 1.2)
                    color = BORDER if edge > 0.5 or (radius - 1.2 - math.hypot(
                        x - min(max(x, radius), size - radius), y - min(max(y, radius), size - radius)) < 0) else BG
                    d = min(_seg_dist(x, y, *pts[k], *pts[k + 1]) for k in range(len(pts) - 1))
                    if d < stroke / 2:
                        color = LINE
                    for c in range(3):
                        acc[c] += color[c] * a
                    acc[3] += a
            n = ss * ss
            alpha = acc[3] / n
            rgb = [int(acc[c] / acc[3]) if acc[3] else 0 for c in range(3)]
            row += bytes(rgb + [int(alpha * 255)])
        rows.append(bytes(row))
    raw = b''.join(rows)

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def build_ico(path: Path, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    frames = [render(s) for s in sizes]
    header = struct.pack('<HHH', 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries, blobs = b'', b''
    for size, data in zip(sizes, frames):
        entries += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + blobs)


if __name__ == '__main__':
    out = Path(__file__).resolve().parent.parent / 'assets' / 'codex-pulse.ico'
    build_ico(out)
    print(out)
