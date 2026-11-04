"""生成 exe 图标 app.ico（需要 Pillow）。

用法::

    python scripts/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    raise SystemExit("需要 Pillow：pip install pillow")

ROOT = Path(__file__).resolve().parents[1]
SIZE = 256
START = (0x8B, 0x7F, 0xFF)
END = (0xEC, 0x48, 0x99)


def build_icon() -> Image.Image:
    gradient = Image.new("RGB", (SIZE, SIZE))
    pixels = gradient.load()
    for y in range(SIZE):
        ratio = y / (SIZE - 1)
        color = tuple(
            int(START[i] + (END[i] - START[i]) * ratio) for i in range(3)
        )
        for x in range(SIZE):
            pixels[x, y] = color

    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [6, 6, SIZE - 6, SIZE - 6], radius=56, fill=255
    )

    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(icon)
    # 白色播放三角
    draw.polygon([(101, 76), (101, 180), (182, 128)], fill=(255, 255, 255, 240))
    # 底部一点高光，避免整体太平
    draw.ellipse([170, 186, 214, 230], fill=(255, 255, 255, 40))
    return icon


def main() -> int:
    icon = build_icon()
    target = ROOT / "app.ico"
    icon.save(
        target,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"已生成 {target} ({target.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
