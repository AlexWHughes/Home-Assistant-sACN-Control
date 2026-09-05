"""Generate a simple square brand icon without third-party image libraries."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 256
BG = (14, 17, 23, 255)
RING = (24, 188, 242, 255)
AMBER = (255, 176, 32, 255)
BAR = (232, 236, 245, 255)


def _px(x: int, y: int) -> tuple[int, int, int, int]:
    cx = cy = (SIZE - 1) / 2
    dx = x - cx
    dy = y - cy
    dist = (dx * dx + dy * dy) ** 0.5
    if dist > 118:
        return (0, 0, 0, 0)
    if dist > 108:
        return RING
    # Three DMX-style level bars
    bars = (
        (86, 168, 34),
        (118, 136, 50),
        (150, 104, 66),
    )
    for left, top, height in bars:
        if left <= x < left + 20 and top <= y < top + height:
            return AMBER if height >= 60 else BAR
    # Small beam above the tallest bar
    if 146 <= x <= 174 and 78 <= y <= 100:
        if abs((x - 160) / 10) + abs((y - 89) / 8) <= 1.2:
            return AMBER
    return BG


def write_png(path: Path, size: int) -> None:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        scale_y = y * SIZE // size
        for x in range(size):
            scale_x = x * SIZE // size
            raw.extend(_px(scale_x, scale_y))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    targets = [
        root / "custom_components" / "sacn_control" / "brand",
        root / "brand",
    ]
    for folder in targets:
        folder.mkdir(parents=True, exist_ok=True)
        write_png(folder / "icon.png", 256)
        write_png(folder / "icon@2x.png", 512)
        write_png(folder / "logo.png", 256)


if __name__ == "__main__":
    main()
