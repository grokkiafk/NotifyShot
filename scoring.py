#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отчёт медика Majestic: раскладка скринов по категориям + подсчёт баллов.

Прогоняет 3 профиля (Таблетки / Вакцинация / ПМП) по видео, раскладывает кадры
по папкам, для ПМП читает игровые часы (clock.py) → День/Ночь, и пишет отчёт.

Локация (ELSH ⟷ Sandy/Paleto) от пользователя НЕ требуется — для таблеток и
вакцин в отчёте показываются оба варианта баллов, выбираешь сам.
"""
import os
import sys
import csv
import tempfile
import shutil

import numpy as np
import cv2

import detector
import clock

# профиль (файл) -> (категория-папка, ключ)
PROFILES = [
    ("heal_majestic.json", "Таблетки", "tablet"),
    ("vaccine_majestic.json", "Вакцинация", "vaccine"),
    ("pmp_majestic.json", "ПМП", "pmp"),
]
PMP_DAY, PMP_NIGHT = 5, 7
TABLET = {"ELSH": 0.5, "Sandy/Paleto": 1.0}
VACCINE = {"ELSH": 2, "Sandy/Paleto": 4}


def _find_events(ffmpeg, ffprobe, video, profile, should_cancel, log):
    size = detector.video_size(ffprobe, video)
    if not size:
        return [], None
    times = detector.keyframe_times(ffprobe, video)
    roi, tpls = detector.compute_roi_and_templates(profile, *size)
    thr = profile.get("threshold", 0.9)
    tmp = tempfile.mkdtemp(prefix="notifyshot_score_")
    try:
        pngs = detector.extract_keyframe_crops(ffmpeg, video, roi, tmp, should_cancel)
        if pngs is None:
            return [], size
        n = min(len(pngs), len(times))
        scores = []
        for i in range(n):
            img = cv2.imread(pngs[i], cv2.IMREAD_GRAYSCALE)
            scores.append(detector.best_score(img, tpls) if img is not None else -1.0)
        return detector.cluster(times[:n], scores, thr), size
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_report(videos, out_dir, ffmpeg=None, ffprobe=None,
               progress=None, log=None, should_cancel=None):
    progress = progress or (lambda x: None)
    log = log or (lambda s: None)
    ffmpeg = ffmpeg or detector.find_tool("ffmpeg")
    ffprobe = ffprobe or detector.find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("Не найден ffmpeg/ffprobe (положите в папку bin).")

    tdir = os.path.join(detector.resource_dir(), "templates")
    profs = []
    for fname, folder, key in PROFILES:
        p = os.path.join(tdir, fname)
        if os.path.isfile(p):
            profs.append((detector.load_profile(p), folder, key))
    clock_tpl = clock.load_templates()
    dow_tpls = clock.load_dow_templates()

    for sub in ("Таблетки", "Вакцинация", os.path.join("ПМП", "День"),
                os.path.join("ПМП", "Ночь"), os.path.join("ПМП", "Время не распознано")):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)

    counts = {"tablet": 0, "vaccine": 0, "pmp_day": 0, "pmp_night": 0, "pmp_unknown": 0}
    rows = []
    total_steps = max(1, len(videos) * len(profs))
    step = 0

    for vi, video in enumerate(videos):
        vname = os.path.basename(video)
        for profile, folder, key in profs:
            if should_cancel and should_cancel():
                break
            log(f"[{vname}] {folder} …")
            events, size = _find_events(ffmpeg, ffprobe, video, profile, should_cancel, log)
            for k, e in enumerate(events):
                t = e["t"]
                hh = int(t // 3600); mm = int(t % 3600 // 60); ss = t % 60
                stamp = f"v{vi+1}_{hh:02d}-{mm:02d}-{ss:04.1f}"
                if key == "pmp":
                    frame_path = os.path.join(out_dir, "_tmp_pmp.png")
                    detector.extract_full_frame(ffmpeg, video, t, frame_path)
                    img = cv2.imdecode(np.fromfile(frame_path, np.uint8), cv2.IMREAD_COLOR) \
                        if os.path.isfile(frame_path) else None
                    hour = clock.read_hour(img, clock_tpl) if img is not None else None
                    weekend = clock.is_weekend(img, dow_tpls) if img is not None else False
                    night = clock.is_night(hour, weekend)
                    if night is None:
                        sub, cat = os.path.join("ПМП", "Время не распознано"), "pmp_unknown"
                        gtime = "??"
                    else:
                        sub = os.path.join("ПМП", "Ночь" if night else "День")
                        cat = "pmp_night" if night else "pmp_day"
                        gtime = f"{hour:02d}ч"
                    name = f"{stamp}_{gtime}.png"
                    dest = os.path.join(out_dir, sub, name)
                    if img is not None:
                        os.replace(frame_path, dest)
                    counts[cat] += 1
                    rows.append([folder, name, f"видео {vi+1}", f"{hh:02d}:{mm:02d}:{ss:04.1f}",
                                 gtime, "ночь" if cat == "pmp_night" else
                                 "день" if cat == "pmp_day" else "?"])
                else:
                    name = f"{stamp}.png"
                    dest = os.path.join(out_dir, folder, name)
                    detector.extract_full_frame(ffmpeg, video, t, dest)
                    counts[key] += 1
                    rows.append([folder, name, f"видео {vi+1}", f"{hh:02d}:{mm:02d}:{ss:04.1f}", "", ""])
            step += 1
            progress(step / total_steps)

    report_text = _write_report(out_dir, counts, rows)
    log(report_text)
    progress(1.0)
    return counts


def _write_report(out_dir, c, rows):
    pmp_pts = c["pmp_day"] * PMP_DAY + c["pmp_night"] * PMP_NIGHT
    lines = [
        "===  ОТЧЁТ ПО БАЛЛАМ  (NotifyShot)  ===", "",
        "ПМП:",
        f"  День:  {c['pmp_day']:>3} × {PMP_DAY} = {c['pmp_day']*PMP_DAY}",
        f"  Ночь:  {c['pmp_night']:>3} × {PMP_NIGHT} = {c['pmp_night']*PMP_NIGHT}",
        f"  Всего ПМП: {c['pmp_day']+c['pmp_night']} шт  →  {pmp_pts} баллов",
    ]
    if c["pmp_unknown"]:
        lines.append(f"  ⚠ Время не распознано: {c['pmp_unknown']} шт — лежат в отдельной папке, разложи вручную.")
    lines += [
        "",
        f"Таблетки: {c['tablet']} шт",
        f"  ELSH: {c['tablet']*TABLET['ELSH']:g}   |   Sandy/Paleto: {c['tablet']*TABLET['Sandy/Paleto']:g}",
        "",
        f"Вакцины: {c['vaccine']} шт",
        f"  ELSH: {c['vaccine']*VACCINE['ELSH']:g}   |   Sandy/Paleto: {c['vaccine']*VACCINE['Sandy/Paleto']:g}",
        "",
        "(Локацию для таблеток/вакцин подставь сам — баллы зависят от неё.)",
    ]
    with open(os.path.join(out_dir, "Отчёт.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(os.path.join(out_dir, "Отчёт.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Категория", "Файл", "Источник", "Тайминг в видео", "Игр.час", "День/Ночь"])
        w.writerows(rows)
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--out", default="notifyshot_report")
    a = ap.parse_args()
    run_report(a.videos, a.out, log=lambda s: print(s),
               progress=lambda x: print(f"\r{x*100:5.1f}%", end="", flush=True))
    print(f"\nГотово: {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
