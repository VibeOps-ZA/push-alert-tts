"""Draw the Push Alert TTS brand icon (a bell with sound waves) using only the
standard library, so it can be regenerated anywhere.

Usage: python3 scripts/make_icon.py custom_components/push_alert_tts/brand
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

TOP = (30, 136, 229)  # #1E88E5
BOTTOM = (13, 71, 161)  # #0D47A1
WHITE = (255, 255, 255)


def _rounded_square(x: float, y: float, radius: float = 0.22) -> bool:
    dx = max(abs(x - 0.5) - (0.5 - radius), 0.0)
    dy = max(abs(y - 0.5) - (0.5 - radius), 0.0)
    return dx * dx + dy * dy <= radius * radius


def _bell(x: float, y: float) -> bool:
    cx = 0.5
    # Knob on top.
    if (x - cx) ** 2 + (y - 0.22) ** 2 <= 0.045**2:
        return True
    # Dome.
    if y <= 0.44 and (x - cx) ** 2 + (y - 0.44) ** 2 <= 0.19**2:
        return True
    # Flaring body.
    if 0.44 <= y <= 0.66:
        half = 0.19 + (y - 0.44) / 0.22 * 0.05
        if abs(x - cx) <= half:
            return True
    # Rim.
    if 0.64 <= y <= 0.70 and abs(x - cx) <= 0.27:
        return True
    # Clapper.
    return (x - cx) ** 2 + (y - 0.755) ** 2 <= 0.055**2


def _waves(x: float, y: float) -> bool:
    cx, cy = 0.5, 0.47
    dx, dy = x - cx, y - cy
    dist = math.hypot(dx, dy)
    if abs(dx) < 0.30:
        return False
    angle = math.degrees(math.atan2(dy, abs(dx)))
    if abs(angle) > 32:
        return False
    return any(abs(dist - r) <= 0.022 for r in (0.355, 0.43))


def _shade(x: float, y: float) -> tuple[int, int, int, int]:
    if not _rounded_square(x, y):
        return (0, 0, 0, 0)
    if _bell(x, y) or _waves(x, y):
        return (*WHITE, 255)
    top, bottom = TOP, BOTTOM
    return (*(round(t + (b - t) * y) for t, b in zip(top, bottom, strict=True)), 255)


def render(size: int, samples: int = 3) -> bytes:
    rows = bytearray()
    step = 1 / (size * samples)
    for py in range(size):
        rows.append(0)  # PNG filter: none
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(samples):
                for sx in range(samples):
                    x = (px * samples + sx + 0.5) * step
                    y = (py * samples + sy + 0.5) * step
                    r, g, b, a = _shade(x, y)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            n = samples * samples
            alpha = acc[3] / n
            if alpha:
                rows += bytes(round(c / acc[3]) for c in acc[:3])
            else:
                rows += b"\x00\x00\x00"
            rows.append(round(alpha))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    (out / "icon.png").write_bytes(render(256))
    (out / "icon@2x.png").write_bytes(render(512))
    print(f"wrote {out / 'icon.png'} and {out / 'icon@2x.png'}")


if __name__ == "__main__":
    main()
