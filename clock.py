#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Чтение игровых часов Majestic из кадра → час → день/ночь.

HUD-часы (формат `ЧЧ:ММ`) висят в фиксированном месте слева внизу. Для
определения день/ночь нужен только ЧАС: поле часа кропается, апскейлится,
бинаризуется, режется на 2 цифры (со сплитом слипшихся) и каждая цифра
сравнивается с эталоном (нормализованный глиф). Разрешение-независимо за счёт
нормализации цифр к фиксированному размеру.

Эталоны цифр лежат в templates/clock/<d>.png. Пересобрать: python clock.py build
"""
import os
import glob

import numpy as np
import cv2

# Координаты при эталонном 1920x1080
HOUR_BOX = (315, 949, 338, 973)
MIN_BOX = (340, 949, 363, 973)
NORM = (20, 30)
REF_W, REF_H = 1920, 1080


def _clock_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    base = getattr(__import__("sys"), "_MEIPASS", here)
    return os.path.join(base, "templates", "clock")


def _field(img, box, sx, sy):
    x0, y0, x1, y1 = box
    crop = img[int(y0*sy):int(y1*sy), int(x0*sx):int(x1*sx)]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)


def _two_digits(g):
    _, b = cv2.threshold(g, 150, 255, cv2.THRESH_BINARY)
    n, _, st, _ = cv2.connectedComponentsWithStats(b, 8)
    H = g.shape[0]
    comps = [tuple(int(st[i, k]) for k in range(4)) for i in range(1, n)
             if st[i, cv2.CC_STAT_HEIGHT] > 0.45 * H and st[i, cv2.CC_STAT_AREA] > 40]
    comps.sort(key=lambda c: c[0])
    if len(comps) >= 2:
        return comps[:2], b
    if len(comps) == 1:
        x, y, w, h = comps[0]
        col = (b[y:y+h, x:x+w] > 0).sum(axis=0)
        lo, hi = int(w * 0.30), int(w * 0.70)
        s = lo + int(np.argmin(col[lo:hi])) if hi > lo else w // 2
        return [(x, y, s, h), (x + s, y, w - s, h)], b
    return comps, b


def _norm(b_img, box):
    x, y, w, h = box
    return cv2.resize(b_img[y:y+h, x:x+w], NORM, interpolation=cv2.INTER_AREA).astype(float)


def load_templates(clock_dir=None):
    clock_dir = clock_dir or _clock_dir()
    tpl = {}
    for p in glob.glob(os.path.join(clock_dir, "[0-9].png")):
        d = os.path.splitext(os.path.basename(p))[0]
        im = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_GRAYSCALE)
        if im is not None:
            tpl[d] = im.astype(float)
    return tpl


def _read2(img, box, tpl, sx, sy):
    boxes, b = _two_digits(_field(img, box, sx, sy))
    if len(boxes) != 2:
        return None
    out = []
    for bx in boxes:
        nd = _norm(b, bx)
        out.append(min(tpl, key=lambda d: np.mean((nd - tpl[d]) ** 2)))
    return out[0] + out[1]


def read_hour(frame_bgr, tpl):
    """Час 0..23 или None."""
    h, w = frame_bgr.shape[:2]
    sx, sy = w / REF_W, h / REF_H
    s = _read2(frame_bgr, HOUR_BOX, tpl, sx, sy)
    if s is None:
        return None
    try:
        hh = int(s)
        return hh if 0 <= hh <= 23 else None
    except ValueError:
        return None


def is_night(hour, weekend=False):
    """True = ночь. Будни: день 10–22. Выходные: день 12–24."""
    if hour is None:
        return None
    start = 12 if weekend else 10
    return not (start <= hour < (24 if weekend else 22))


# --- день недели: выходной? (Суббота/Воскресенье) -------------------------- #
DOW_BOX = (314, 972, 480, 998)
DOW_SCALES = (0.9, 0.95, 1.0, 1.05, 1.1)


def load_dow_templates(clock_dir=None):
    clock_dir = clock_dir or _clock_dir()
    out = []
    for nm in ("dow_sat.png", "dow_sun.png"):
        p = os.path.join(clock_dir, nm)
        if os.path.isfile(p):
            im = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_GRAYSCALE)
            if im is not None:
                out.append(im)
    return out


def is_weekend(frame_bgr, dow_tpls, threshold=0.66):
    """True, если в кадре день недели = Суббота/Воскресенье."""
    if not dow_tpls:
        return False
    h, w = frame_bgr.shape[:2]
    sx, sy = w / REF_W, h / REF_H
    x0, y0, x1, y1 = DOW_BOX
    g = cv2.cvtColor(frame_bgr[int(y0*sy):int(y1*sy), int(x0*sx):int(x1*sx)],
                     cv2.COLOR_BGR2GRAY)
    best = 0.0
    for t in dow_tpls:
        for s in DOW_SCALES:
            ts = cv2.resize(t, None, fx=sx*s, fy=sy*s, interpolation=cv2.INTER_AREA)
            if ts.shape[0] <= g.shape[0] and ts.shape[1] <= g.shape[1]:
                best = max(best, float(cv2.matchTemplate(g, ts, cv2.TM_CCOEFF_NORMED).max()))
    return best >= threshold


# --------------------------------------------------------------------------- #
def _build(out_dir):
    """Пересобрать эталоны цифр из размеченных кадров C:\\tmp\\hf_*.png."""
    frames = [(rf"C:\tmp\hf_{i}.png", t) for i, t in enumerate(
        ["0131", "0148", "0204", "0220", "0237", "0253", "0309", "0326"])]
    os.makedirs(out_dir, exist_ok=True)
    saved = {}
    for path, t in frames:
        img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        for box, lbl in ((HOUR_BOX, t[:2]), (MIN_BOX, t[2:])):
            boxes, b = _two_digits(_field(img, box, 1.0, 1.0))
            if len(boxes) != 2:
                continue
            for d, bx in zip(lbl, boxes):
                if d not in saved:
                    saved[d] = True
                    arr = _norm(b, bx).astype(np.uint8)
                    cv2.imencode(".png", arr)[1].tofile(os.path.join(out_dir, f"{d}.png"))
    print("saved digits:", "".join(sorted(saved)))


def _selftest():
    tpl = load_templates()
    frames = [(rf"C:\tmp\hf_{i}.png", t) for i, t in enumerate(
        ["0131", "0148", "0204", "0220", "0237", "0253", "0309", "0326"])]
    ok = 0
    for path, t in frames:
        img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        hh = read_hour(img, tpl)
        good = hh == int(t[:2])
        ok += good
        print(f"  {t[:2]}:{t[2:]} -> час {hh}  night={is_night(hh)}  {'OK' if good else 'X'}")
    print(f"итог: {ok}/{len(frames)}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        _build(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "templates", "clock"))
    _selftest()
