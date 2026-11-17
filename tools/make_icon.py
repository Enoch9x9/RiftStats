"""生成应用图标：深海军蓝底 + 海克斯金渐变柱状图 + 环。

跑一次会在 assets/ 下产出 riftstats.png（256）和 riftstats.ico（多尺寸）。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
S = 1024  # 先画大图再缩小，边缘才干净

BG_TOP = (16, 28, 46)
BG_BOTTOM = (7, 13, 20)
GOLD = (200, 170, 110)
GOLD_HI = (232, 208, 156)
GOLD_DIM = (138, 116, 70)


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    return mask


def vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(size):
            px[x, y] = color
    return img


def build() -> Image.Image:
    img = vertical_gradient(S, BG_TOP, BG_BOTTOM).convert("RGBA")

    # 背景上的微弱光晕
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([S * 0.18, S * 0.10, S * 0.82, S * 0.74], fill=(63, 169, 245, 26))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.06))
    img = Image.alpha_composite(img, glow)

    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # 金色圆环（细，带缺口，像仪表盘）
    ring_box = [S * 0.13, S * 0.13, S * 0.87, S * 0.87]
    d.arc(ring_box, start=200, end=340, fill=(*GOLD_DIM, 200), width=int(S * 0.022))
    d.arc(ring_box, start=20, end=160, fill=(*GOLD, 235), width=int(S * 0.022))

    # 三根上升的柱子
    bars = [
        (0.255, 0.44),
        (0.435, 0.30),
        (0.615, 0.17),
    ]
    w = S * 0.125
    base_y = S * 0.70
    for x_ratio, top_ratio in bars:
        x0 = S * x_ratio
        y0 = S * top_ratio
        d.rounded_rectangle(
            [x0, y0, x0 + w, base_y],
            radius=int(w * 0.30),
            fill=(*GOLD, 255),
        )

    # 柱顶高光
    for x_ratio, top_ratio in bars:
        x0 = S * x_ratio
        y0 = S * top_ratio
        d.rounded_rectangle(
            [x0, y0, x0 + w, y0 + S * 0.032],
            radius=int(w * 0.20),
            fill=(*GOLD_HI, 255),
        )

    # 底部基线
    d.rounded_rectangle(
        [S * 0.22, base_y + S * 0.03, S * 0.78, base_y + S * 0.055],
        radius=int(S * 0.012),
        fill=(*GOLD_DIM, 200),
    )

    img = Image.alpha_composite(img, layer)

    # 圆角裁切
    img.putalpha(rounded_mask(S, int(S * 0.22)))
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    big = build()
    png = ASSETS / "riftstats.png"
    ico = ASSETS / "riftstats.ico"
    big.resize((256, 256), Image.LANCZOS).save(png)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    big.resize((256, 256), Image.LANCZOS).save(ico, format="ICO", sizes=sizes)
    print("saved", png, png.stat().st_size, "bytes")
    print("saved", ico, ico.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
