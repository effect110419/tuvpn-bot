# -*- coding: utf-8 -*-
"""
Генератор футуристичных обложек для постов @tuvpn_news.

Чистый PIL, без внешних API: тёмный фон, неоновые свечения,
перспективная сетка, крупный заголовок (акцентные слова в *звёздочках*),
брендинг TuVPN. Палитра и мотив приходят из news_topics.py.

generate_cover(title, subtitle, palette, motif, seed) -> bytes (PNG)
"""

import io
import os
import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

BG_TOP = (10, 13, 28)
BG_BOTTOM = (16, 12, 38)
TEXT_MAIN = (244, 246, 255)
TEXT_DIM = (150, 158, 190)


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)


# ── базовые слои ─────────────────────────────────────────────────────

def _gradient_bg() -> Image.Image:
    """Вертикальный градиент фона."""
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / H
        grad.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    return grad.resize((W, H))


def _add_glow(img: Image.Image, cx: int, cy: int, r: int, color: tuple, alpha: int, blur: int = 160):
    """Мягкое неоновое пятно света."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer)


def _add_grid(img: Image.Image, color: tuple, rng: random.Random):
    """Перспективная сетка-«пол» в нижней части."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    horizon = H - rng.randint(210, 260)
    vx = rng.randint(W // 2 - 150, W // 2 + 250)  # точка схода

    for i in range(-14, 15):
        x_bottom = vx + i * 170
        d.line([(vx, horizon), (x_bottom, H)], fill=color + (26,), width=2)
    y = horizon
    step = 7.0
    while y < H:
        a = int(14 + (y - horizon) / (H - horizon) * 26)
        d.line([(0, int(y)), (W, int(y))], fill=color + (a,), width=1)
        y += step
        step *= 1.38
    # линия горизонта чуть ярче + свечение
    d.line([(0, horizon), (W, horizon)], fill=color + (60,), width=2)
    layer = layer.filter(ImageFilter.GaussianBlur(0.6))
    img.alpha_composite(layer)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line([(0, horizon), (W, horizon)], fill=color + (70,), width=6)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))


def _add_particles(img: Image.Image, colors: list, rng: random.Random, n: int = 90):
    """Звёзды/частицы."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y = rng.randint(0, W), rng.randint(0, H - 260)
        r = rng.choice([1, 1, 1, 2, 2, 3])
        a = rng.randint(28, 110)
        c = rng.choice(colors + [(220, 226, 250)])
        d.ellipse([x - r, y - r, x + r, y + r], fill=c + (a,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.5)))


def _add_orbits(img: Image.Image, color: tuple, rng: random.Random):
    """Декоративные дуги-орбиты в правом верхнем углу."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = W - rng.randint(60, 160), rng.randint(30, 120)
    for i, r in enumerate((140, 210, 290, 380)):
        a = 40 - i * 8
        d.arc([cx - r, cy - r, cx + r, cy + r], start=60, end=290, fill=color + (a,), width=2)
    # точка-спутник на второй орбите
    ang = math.radians(rng.randint(120, 250))
    px, py = cx + 210 * math.cos(ang), cy + 210 * math.sin(ang)
    d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=color + (170,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.4)))


def _add_scanlines(img: Image.Image):
    """Едва заметные горизонтальные сканлайны — «экранная» фактура."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for y in range(0, H, 4):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, 14), width=1)
    img.alpha_composite(layer)


def _vignette(img: Image.Image):
    """Затемнение краёв."""
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-W * 0.35, -H * 0.45, W * 1.35, H * 1.45], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(180))
    dark = Image.new("RGBA", (W, H), (2, 3, 10, 200))
    dark.putalpha(Image.eval(mask, lambda v: int((255 - v) * 0.78)))
    img.alpha_composite(dark)


# ── мотивы (крупный полупрозрачный глиф справа) ──────────────────────

def _motif_layer(motif: str, color: tuple, color2: tuple) -> Image.Image:
    """Рисует глиф ~420px в правой части, контурный стиль + свечение."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy, s = 1010, 360, 190  # центр и радиус глифа
    w_main = 10
    c = color + (78,)
    c2 = color2 + (60,)

    if motif == "shield":
        pts = [(cx, cy - s), (cx + s * 0.82, cy - s * 0.62), (cx + s * 0.82, cy + s * 0.18),
               (cx, cy + s), (cx - s * 0.82, cy + s * 0.18), (cx - s * 0.82, cy - s * 0.62)]
        d.polygon(pts, outline=c, width=w_main)
        d.line([(cx - s * 0.34, cy - s * 0.02), (cx - s * 0.06, cy + s * 0.28), (cx + s * 0.4, cy - s * 0.34)],
               fill=c2, width=w_main + 2, joint="curve")
    elif motif == "lock":
        d.rounded_rectangle([cx - s * 0.7, cy - s * 0.15, cx + s * 0.7, cy + s * 0.85], radius=34, outline=c, width=w_main)
        d.arc([cx - s * 0.45, cy - s * 0.95, cx + s * 0.45, cy + s * 0.05], start=180, end=360, fill=c, width=w_main)
        d.line([(cx - s * 0.45 + w_main // 2, cy - s * 0.45), (cx - s * 0.45 + w_main // 2, cy - s * 0.15)], fill=c, width=w_main)
        d.line([(cx + s * 0.45 - w_main // 2, cy - s * 0.45), (cx + s * 0.45 - w_main // 2, cy - s * 0.15)], fill=c, width=w_main)
        d.ellipse([cx - 16, cy + s * 0.22, cx + 16, cy + s * 0.42], outline=c2, width=8)
    elif motif == "play":
        d.ellipse([cx - s, cy - s, cx + s, cy + s], outline=c, width=w_main)
        d.polygon([(cx - s * 0.28, cy - s * 0.42), (cx + s * 0.5, cy), (cx - s * 0.28, cy + s * 0.42)],
                  outline=c2, width=w_main)
    elif motif == "globe":
        d.ellipse([cx - s, cy - s, cx + s, cy + s], outline=c, width=w_main)
        d.ellipse([cx - s * 0.42, cy - s, cx + s * 0.42, cy + s], outline=c2, width=6)
        d.line([(cx - s, cy), (cx + s, cy)], fill=c2, width=6)
        d.arc([cx - s, cy - s * 0.62, cx + s, cy + s * 0.1], start=0, end=180, fill=c2, width=6)
        d.arc([cx - s, cy - s * 0.1, cx + s, cy + s * 0.62], start=180, end=360, fill=c2, width=6)
    elif motif == "bolt":
        pts = [(cx + s * 0.18, cy - s), (cx - s * 0.5, cy + s * 0.12), (cx - s * 0.08, cy + s * 0.12),
               (cx - s * 0.18, cy + s), (cx + s * 0.5, cy - s * 0.12), (cx + s * 0.08, cy - s * 0.12)]
        d.polygon(pts, outline=c, width=w_main)
    elif motif == "users":
        d.ellipse([cx - s * 0.55, cy - s * 0.8, cx + s * 0.05, cy - s * 0.2], outline=c, width=w_main)
        d.arc([cx - s * 0.85, cy - s * 0.1, cx + s * 0.35, cy + s * 0.9], start=180, end=360, fill=c, width=w_main)
        d.ellipse([cx + s * 0.25, cy - s * 0.65, cx + s * 0.75, cy - s * 0.15], outline=c2, width=8)
        d.arc([cx + s * 0.05, cy - s * 0.05, cx + s * 0.95, cy + s * 0.75], start=180, end=340, fill=c2, width=8)
    elif motif == "battery":
        d.rounded_rectangle([cx - s * 0.85, cy - s * 0.45, cx + s * 0.65, cy + s * 0.45], radius=26, outline=c, width=w_main)
        d.rounded_rectangle([cx + s * 0.72, cy - s * 0.18, cx + s * 0.88, cy + s * 0.18], radius=8, outline=c, width=8)
        for i in range(3):
            x0 = cx - s * 0.68 + i * s * 0.42
            d.rounded_rectangle([x0, cy - s * 0.28, x0 + s * 0.3, cy + s * 0.28], radius=10, fill=color2 + (46,))
    elif motif == "rocket":
        d.arc([cx - s * 0.55, cy - s, cx + s * 0.55, cy + s * 0.7], start=250, end=290, fill=c, width=w_main)
        d.line([(cx - s * 0.16, cy - s * 0.92), (cx - s * 0.16, cy + s * 0.45)], fill=c, width=w_main)
        d.line([(cx + s * 0.16, cy - s * 0.92), (cx + s * 0.16, cy + s * 0.45)], fill=c, width=w_main)
        d.polygon([(cx - s * 0.16, cy + s * 0.1), (cx - s * 0.5, cy + s * 0.6), (cx - s * 0.16, cy + s * 0.45)], outline=c2, width=8)
        d.polygon([(cx + s * 0.16, cy + s * 0.1), (cx + s * 0.5, cy + s * 0.6), (cx + s * 0.16, cy + s * 0.45)], outline=c2, width=8)
        d.ellipse([cx - s * 0.09, cy - s * 0.5, cx + s * 0.09, cy - s * 0.32], outline=c2, width=7)
        d.line([(cx, cy + s * 0.55), (cx, cy + s * 0.9)], fill=c2, width=10)
    elif motif == "chat":
        d.rounded_rectangle([cx - s * 0.9, cy - s * 0.7, cx + s * 0.6, cy + s * 0.35], radius=44, outline=c, width=w_main)
        d.polygon([(cx - s * 0.45, cy + s * 0.33), (cx - s * 0.2, cy + s * 0.68), (cx - s * 0.1, cy + s * 0.33)], outline=c, width=8)
        for i in range(3):
            x0 = cx - s * 0.55 + i * s * 0.4
            d.ellipse([x0, cy - s * 0.24, x0 + 18, cy - s * 0.06], fill=c2)
    elif motif == "grid_apps":
        for gx in range(2):
            for gy in range(2):
                x0 = cx - s * 0.85 + gx * s * 0.95
                y0 = cy - s * 0.85 + gy * s * 0.95
                cc = c if (gx + gy) % 2 == 0 else c2
                d.rounded_rectangle([x0, y0, x0 + s * 0.75, y0 + s * 0.75], radius=30, outline=cc, width=w_main)
        d.line([(cx + s * 0.42, cy + s * 0.32), (cx + s * 0.42, cy + s * 0.72)], fill=c, width=9)
        d.line([(cx + s * 0.22, cy + s * 0.52), (cx + s * 0.62, cy + s * 0.52)], fill=c, width=9)
    elif motif == "server":
        for i, y0 in enumerate((-0.95, -0.28, 0.39)):
            d.rounded_rectangle([cx - s * 0.85, cy + s * y0, cx + s * 0.85, cy + s * (y0 + 0.55)],
                                radius=22, outline=(c if i != 1 else c2), width=w_main)
            d.ellipse([cx - s * 0.68, cy + s * (y0 + 0.2), cx - s * 0.52, cy + s * (y0 + 0.36)],
                      fill=color2 + (90,) if i == 1 else color + (90,))
            d.line([(cx + s * 0.1, cy + s * (y0 + 0.28)), (cx + s * 0.65, cy + s * (y0 + 0.28))], fill=c2, width=7)
    elif motif == "gift":
        d.rounded_rectangle([cx - s * 0.8, cy - s * 0.25, cx + s * 0.8, cy + s * 0.9], radius=24, outline=c, width=w_main)
        d.line([(cx - s * 0.8, cy + s * 0.12), (cx + s * 0.8, cy + s * 0.12)], fill=c, width=8)
        d.line([(cx, cy - s * 0.25), (cx, cy + s * 0.9)], fill=c2, width=8)
        d.ellipse([cx - s * 0.5, cy - s * 0.72, cx - s * 0.02, cy - s * 0.2], outline=c2, width=9)
        d.ellipse([cx + s * 0.02, cy - s * 0.72, cx + s * 0.5, cy - s * 0.2], outline=c2, width=9)
    elif motif == "question":
        d.arc([cx - s * 0.55, cy - s * 0.95, cx + s * 0.55, cy + s * 0.1], start=150, end=450, fill=c, width=w_main + 4)
        d.line([(cx, cy + s * 0.08), (cx, cy + s * 0.42)], fill=c, width=w_main + 4)
        d.ellipse([cx - 13, cy + s * 0.62, cx + 13, cy + s * 0.84], fill=c2)
    elif motif == "radar":
        for r_ in (s * 0.35, s * 0.68, s):
            d.ellipse([cx - r_, cy - r_, cx + r_, cy + r_], outline=c, width=6)
        d.line([(cx, cy), (cx + s * 0.82, cy - s * 0.55)], fill=c2, width=8)
        d.pieslice([cx - s, cy - s, cx + s, cy + s], start=-58, end=-18, fill=color2 + (26,))
        d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=c2)
        d.ellipse([cx - s * 0.42 - 7, cy + s * 0.3 - 7, cx - s * 0.42 + 7, cy + s * 0.3 + 7], fill=color + (150,))
    elif motif == "wall":
        bw, bh = s * 0.62, s * 0.34
        for row in range(4):
            off = (bw / 2) if row % 2 else 0
            for col in range(-1, 3):
                x0 = cx - s * 0.9 + col * bw + off
                y0 = cy - s * 0.75 + row * bh
                cc = c2 if (row == 1 and col == 1) else c
                d.rounded_rectangle([x0 + 4, y0 + 4, x0 + bw - 4, y0 + bh - 4], radius=8, outline=cc, width=6)
        d.line([(cx - s * 0.2, cy - s * 0.05), (cx + s * 0.55, cy + s * 0.6)], fill=c2, width=10)
        d.line([(cx + s * 0.55, cy - s * 0.05), (cx - s * 0.2, cy + s * 0.6)], fill=c2, width=10)
    elif motif == "eye":
        d.arc([cx - s, cy - s * 0.9, cx + s, cy + s * 0.9], start=25, end=155, fill=c, width=w_main)
        d.arc([cx - s, cy - s * 0.9, cx + s, cy + s * 0.9], start=205, end=335, fill=c, width=w_main)
        d.ellipse([cx - s * 0.32, cy - s * 0.32, cx + s * 0.32, cy + s * 0.32], outline=c2, width=w_main)
        d.ellipse([cx - s * 0.1, cy - s * 0.1, cx + s * 0.1, cy + s * 0.1], fill=c2)
    elif motif == "briefcase":
        d.rounded_rectangle([cx - s * 0.85, cy - s * 0.4, cx + s * 0.85, cy + s * 0.7], radius=26, outline=c, width=w_main)
        d.line([(cx - s * 0.85, cy + s * 0.08), (cx + s * 0.85, cy + s * 0.08)], fill=c, width=7)
        d.rounded_rectangle([cx - s * 0.3, cy - s * 0.75, cx + s * 0.3, cy - s * 0.4], radius=14, outline=c2, width=8)
        d.rounded_rectangle([cx - s * 0.12, cy - s * 0.02, cx + s * 0.12, cy + s * 0.22], radius=8, fill=color2 + (60,))
    elif motif == "warning":
        pts = [(cx, cy - s), (cx + s * 0.95, cy + s * 0.75), (cx - s * 0.95, cy + s * 0.75)]
        d.polygon(pts, outline=c, width=w_main)
        d.line([(cx, cy - s * 0.4), (cx, cy + s * 0.22)], fill=c2, width=14)
        d.ellipse([cx - 11, cy + s * 0.4, cx + 11, cy + s * 0.62], fill=c2)
    elif motif == "search":
        d.ellipse([cx - s * 0.85, cy - s * 0.85, cx + s * 0.35, cy + s * 0.35], outline=c, width=w_main)
        d.line([(cx + s * 0.28, cy + s * 0.28), (cx + s * 0.85, cy + s * 0.85)], fill=c, width=w_main + 6)
        d.arc([cx - s * 0.62, cy - s * 0.62, cx + s * 0.12, cy + s * 0.12], start=180, end=270, fill=c2, width=8)
    elif motif == "layers":
        for i, dy in enumerate((-0.45, 0.0, 0.45)):
            a = 78 - i * 14
            pts = [(cx, cy + s * (dy - 0.42)), (cx + s * 0.9, cy + s * dy),
                   (cx, cy + s * (dy + 0.42)), (cx - s * 0.9, cy + s * dy)]
            d.polygon(pts, outline=(color if i % 2 == 0 else color2) + (a,), width=w_main - 2)
    else:  # fallback — кольцо
        d.ellipse([cx - s, cy - s, cx + s, cy + s], outline=c, width=w_main)

    glow = layer.filter(ImageFilter.GaussianBlur(16))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(layer)
    return out


# ── текст ────────────────────────────────────────────────────────────

def _parse_accents(title: str) -> list:
    """Разбивает строку на токены [(word, is_accent)] по *маркерам*."""
    tokens = []
    for part in title.replace("\n", " ").split(" "):
        if not part:
            continue
        if part.startswith("*") and part.endswith("*") and len(part) > 2:
            tokens.append((part.strip("*"), True))
        else:
            tokens.append((part.replace("*", ""), False))
    return tokens


def _wrap_tokens(tokens: list, font: ImageFont.FreeTypeFont, max_w: int, d: ImageDraw.ImageDraw) -> list:
    """Перенос по словам под ширину. Возвращает список строк-списков токенов."""
    lines, cur = [], []
    for tok in tokens:
        trial = " ".join(t[0] for t in cur + [tok])
        if cur and d.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = [tok]
        else:
            cur.append(tok)
    if cur:
        lines.append(cur)
    return lines


def _draw_headline(img: Image.Image, title: str, subtitle: str, accent: tuple):
    d = ImageDraw.Draw(img)
    tokens = _parse_accents(title)
    max_w = 760

    # адаптивный размер: пробуем от большого к меньшему, чтобы влезть в 3 строки
    size = 86
    while size >= 54:
        font = _font("Montserrat-ExtraBold.ttf", size)
        lines = _wrap_tokens(tokens, font, max_w, d)
        if len(lines) <= 3:
            break
        size -= 6
    line_h = int(size * 1.22)
    total_h = line_h * len(lines)
    x0 = 72
    y0 = (H - total_h) // 2 - 40

    # свечение под текстом
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    y = y0
    for line in lines:
        x = x0
        for word, is_acc in line:
            wtxt = word + " "
            gd.text((x, y), word, font=font, fill=(accent if is_acc else (120, 140, 255)) + (110,))
            x += d.textlength(wtxt, font=font)
        y += line_h
    img.alpha_composite(glow_layer.filter(ImageFilter.GaussianBlur(22)))

    # основной текст
    d = ImageDraw.Draw(img)
    y = y0
    for line in lines:
        x = x0
        for word, is_acc in line:
            d.text((x, y), word, font=font, fill=(accent + (255,)) if is_acc else (TEXT_MAIN + (255,)))
            x += d.textlength(word + " ", font=font)
        y += line_h

    # акцентная полоска
    bar_y = y + 18
    d.rounded_rectangle([x0, bar_y, x0 + 140, bar_y + 8], radius=4, fill=accent + (230,))

    # подзаголовок
    if subtitle:
        sub_font = _font("Montserrat-Medium.ttf", 30)
        d.text((x0, bar_y + 30), subtitle, font=sub_font, fill=TEXT_DIM + (255,))


def _draw_brand(img: Image.Image, accent: tuple):
    """Бейдж TuVPN сверху слева + футер снизу. Рисуем на слое, чтобы альфа смешивалась."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f_brand = _font("Montserrat-ExtraBold.ttf", 30)
    f_tag = _font("Montserrat-Medium.ttf", 22)

    # пилюля
    bx, by = 64, 48
    brand_txt = "TuVPN"
    tw = d.textlength(brand_txt, font=f_brand)
    pill_w = int(tw + 92)
    d.rounded_rectangle([bx, by, bx + pill_w, by + 56], radius=28,
                        fill=(255, 255, 255, 16), outline=accent + (110,), width=2)
    # неоновая точка со свечением
    dot_x, dot_y = bx + 30, by + 28
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([dot_x - 10, dot_y - 10, dot_x + 10, dot_y + 10], fill=accent + (255,))
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(7)))
    d = ImageDraw.Draw(layer)
    d.ellipse([dot_x - 7, dot_y - 7, dot_x + 7, dot_y + 7], fill=accent + (255,))
    d.text((bx + 52, by + 11), brand_txt, font=f_brand, fill=TEXT_MAIN + (255,))
    # канал справа от пилюли
    d.text((bx + pill_w + 18, by + 17), "@tuvpn_news", font=f_tag, fill=TEXT_DIM + (200,))

    # футер
    f_foot = _font("Montserrat-SemiBold.ttf", 24)
    d.text((64, H - 66), "@MaxArtVPN_bot  ·  7 дней бесплатно", font=f_foot, fill=TEXT_DIM + (235,))
    img.alpha_composite(layer)


# ── сборка ───────────────────────────────────────────────────────────

def generate_cover(title: str, subtitle: str = "", palette=("#22d3ee", "#8b5cf6"),
                   motif: str = "shield", seed: int | None = None) -> bytes:
    """Собирает обложку, возвращает PNG-байты."""
    rng = random.Random(seed)
    a1, a2 = _hex(palette[0]), _hex(palette[1])

    img = _gradient_bg().convert("RGBA")

    # неоновые пятна: основное за глифом, вторичное слева-снизу, третье сверху
    _add_glow(img, 1020, 340, 330, a1, 60)
    _add_glow(img, rng.randint(80, 260), H - rng.randint(60, 160), 300, a2, 52)
    _add_glow(img, rng.randint(300, 700), rng.randint(-80, 40), 260, a2, 36)

    _add_particles(img, [a1, a2], rng)
    _add_orbits(img, a1, rng)
    _add_grid(img, a1 if rng.random() < 0.6 else a2, rng)
    img.alpha_composite(_motif_layer(motif, a1, a2))

    _vignette(img)
    _draw_headline(img, title, subtitle, a1)
    _draw_brand(img, a1)
    _add_scanlines(img)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


if __name__ == "__main__":
    # локальный тест: рендер всех мотивов
    import sys
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/covers"
    os.makedirs(out_dir, exist_ok=True)
    from news_topics import TOPICS
    for t in TOPICS[:6]:
        png = generate_cover(t["title"], "Разбираемся простыми словами", t["palette"], t["motif"], seed=42)
        with open(os.path.join(out_dir, f"{t['id']}.png"), "wb") as f:
            f.write(png)
        print(t["id"], len(png))
