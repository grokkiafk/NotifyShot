#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Генерирует иконку NotifyShot: розовый «видоискатель» (рамка кадра + точка).

Запуск:  python make_icon.py   ->  assets/notifyshot.ico + assets/logo.png
"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
PINK = (232, 24, 92, 255)
WHITE = (255, 255, 255, 255)


def make(S=1024):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # фон — скруглённый квадрат фирменного розового
    pad = int(S * 0.04)
    d.rounded_rectangle([pad, pad, S - pad, S - pad],
                        radius=int(S * 0.22), fill=PINK)
    # уголки кадра (видоискатель)
    m = int(S * 0.25)         # отступ от края
    arm = int(S * 0.16)       # длина плеча
    w = int(S * 0.072)        # толщина
    r = w // 2

    def corner(cx, cy, dx, dy):
        d.rounded_rectangle([min(cx, cx + dx * arm) - r, cy - r,
                             max(cx, cx + dx * arm) + r, cy + r],
                            radius=r, fill=WHITE)
        d.rounded_rectangle([cx - r, min(cy, cy + dy * arm) - r,
                             cx + r, max(cy, cy + dy * arm) + r],
                            radius=r, fill=WHITE)

    corner(m, m, 1, 1)
    corner(S - m, m, -1, 1)
    corner(m, S - m, 1, -1)
    corner(S - m, S - m, -1, -1)
    # точка фокуса по центру
    rr = int(S * 0.10)
    c = S // 2
    d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=WHITE)
    return img


def main():
    os.makedirs(ASSETS, exist_ok=True)
    img = make(1024)
    img.save(os.path.join(ASSETS, "logo.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = img.resize((256, 256), Image.LANCZOS)
    base.save(os.path.join(ASSETS, "notifyshot.ico"),
              sizes=[(s, s) for s in sizes])
    print("saved assets/logo.png + assets/notifyshot.ico")


if __name__ == "__main__":
    main()
