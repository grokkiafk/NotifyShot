#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NotifyShot detection core.

Finds a recurring on-screen notification inside long gameplay recordings and
saves one (or a few) full-resolution PNG screenshot(s) per occurrence.

A "profile" describes what to look for AND where:
    {
      "name":     human label,
      "image":    template png (a tight crop of the constant part of the toast),
      "box":      [x, y, w, h]  position of that crop in the source frame,
      "src_size": [W, H]        size of the source frame the box was taken from,
      "pad":      [horiz, up, down]  search-band padding, in box-size units
    }

Detection scales the box + template to each video's real resolution and only
searches that band at (near) native scale. This keeps the sharp text detail
that makes the match reliable, while staying resolution/position independent.

Only keyframes are decoded (≈1 every 2s), so 6 hours of footage is minutes of
work, not hours.

No GUI here — imported by the app, and runnable from the command line.
"""
import os
import sys
import glob
import json
import shutil
import tempfile
import argparse
import subprocess

import numpy as np
import cv2

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Sensitivity preset -> match threshold (TM_CCOEFF_NORMED).
SENSITIVITY = {"low": 0.74, "med": 0.82, "high": 0.88}

# Small scale jitter to absorb resolution differences between the profile's
# source frame and the actual video.
SCALE_JITTER = (0.93, 1.0, 1.08)

VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".avi", ".m4v", ".webm", ".ts", ".flv")


# --------------------------------------------------------------------------- #
# Tool / path helpers
# --------------------------------------------------------------------------- #
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir():
    return getattr(sys, "_MEIPASS", app_dir())


def find_tool(name):
    exe = name + (".exe" if os.name == "nt" else "")
    for c in (os.path.join(app_dir(), "bin", exe),
              os.path.join(app_dir(), exe),
              os.path.join(resource_dir(), "bin", exe)):
        if os.path.isfile(c):
            return c
    return shutil.which(name)


def _run(cmd):
    return subprocess.run(cmd, creationflags=CREATE_NO_WINDOW,
                          capture_output=True, text=True)


def _popen(cmd):
    return subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
def load_profile(path):
    with open(path, "r", encoding="utf-8") as f:
        prof = json.load(f)
    img_path = os.path.join(os.path.dirname(path), prof["image"])
    tpl = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        raise RuntimeError(f"Не удалось открыть картинку шаблона: {img_path}")
    prof.setdefault("pad", [1.5, 5.0, 1.5])
    prof["_tpl"] = tpl
    prof["_path"] = path
    return prof


def list_profiles(*dirs):
    found = {}
    for d in dirs:
        if d and os.path.isdir(d):
            for p in sorted(glob.glob(os.path.join(d, "*.json"))):
                found[os.path.basename(p)] = p   # later dirs override by name
    return list(found.values())


# --------------------------------------------------------------------------- #
# ffprobe / ffmpeg steps
# --------------------------------------------------------------------------- #
def video_size(ffprobe, video):
    out = _run([ffprobe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", video])
    try:
        w, h = out.stdout.strip().split("x")[:2]
        return int(w), int(h)
    except Exception:
        return None


def keyframe_times(ffprobe, video):
    out = _run([ffprobe, "-v", "error", "-select_streams", "v:0",
                "-skip_frame", "nokey", "-show_entries", "frame=pts_time",
                "-of", "csv=p=0", video])
    times = []
    for ln in out.stdout.splitlines():
        ln = ln.strip().strip(",")
        if ln:
            try:
                times.append(float(ln))
            except ValueError:
                pass
    return times


def extract_keyframe_crops(ffmpeg, video, roi, tmpdir, should_cancel, on_count=None):
    """Decode ONLY keyframes, crop to ROI band, save grayscale PNGs.

    on_count(n) is called periodically with the number of frames written so
    far, so the caller can show real progress during this (slow) step.
    """
    for f in glob.glob(os.path.join(tmpdir, "k_*.png")):
        os.remove(f)
    X, Y, W, H = roi
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-skip_frame", "nokey",
           "-i", video, "-an", "-vf", f"crop={W}:{H}:{X}:{Y}",
           "-pix_fmt", "gray", "-vsync", "0",
           os.path.join(tmpdir, "k_%06d.png")]
    p = _popen(cmd)
    while p.poll() is None:
        if should_cancel and should_cancel():
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
            return None
        if on_count:
            try:
                on_count(len(glob.glob(os.path.join(tmpdir, "k_*.png"))))
            except Exception:
                pass
        try:
            p.wait(0.3)
        except subprocess.TimeoutExpired:
            pass
    out = sorted(glob.glob(os.path.join(tmpdir, "k_*.png")))
    if on_count:
        on_count(len(out))
    return out


def extract_full_frame(ffmpeg, video, t, out_path):
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
          "-ss", f"{max(0.0, t):.3f}", "-i", video, "-frames:v", "1", out_path])


# --------------------------------------------------------------------------- #
# ROI / template math
# --------------------------------------------------------------------------- #
def compute_roi_and_templates(profile, vw, vh):
    """Map the profile's box+template onto a video of size (vw, vh)."""
    sw, sh = profile["src_size"]
    sx, sy = vw / sw, vh / sh
    x, y, w, h = profile["box"]
    ph, pu, pd = profile["pad"]

    bx = x - ph * w
    by = y - pu * h
    bw = w + 2 * ph * w
    bh = h + (pu + pd) * h

    X = int(max(0, round(bx * sx)))
    Y = int(max(0, round(by * sy)))
    W = int(min(vw - X, round(bw * sx)))
    H = int(min(vh - Y, round(bh * sy)))
    # ffmpeg crop wants even dimensions for some pix formats; round down to even.
    W -= W % 2
    H -= H % 2

    tpl = profile["_tpl"]
    tw0 = max(8, int(round(tpl.shape[1] * sx)))
    th0 = max(8, int(round(tpl.shape[0] * sy)))
    base = cv2.resize(tpl, (tw0, th0), interpolation=cv2.INTER_AREA)
    tpls = []
    for m in SCALE_JITTER:
        tw = max(8, int(round(tw0 * m)))
        th = max(8, int(round(th0 * m)))
        if tw < W and th < H:
            t = base if m == 1.0 else cv2.resize(base, (tw, th))
            tpls.append(t)
    if not tpls:
        tpls = [base]
    return (X, Y, W, H), tpls


def best_score(img, tpls):
    best = -1.0
    for t in tpls:
        if t.shape[0] > img.shape[0] or t.shape[1] > img.shape[1]:
            continue
        res = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
        m = float(res.max())
        if m > best:
            best = m
    return best


def cluster(times, scores, threshold, gap=6.0):
    events, cur = [], None
    for i, t in enumerate(times):
        if scores[i] >= threshold:
            if cur and (t - cur["last"]) <= gap:
                cur["last"] = t
                if scores[i] > cur["score"]:
                    cur["t"] = t
                    cur["score"] = scores[i]
            else:
                if cur:
                    events.append(cur)
                cur = {"t": t, "last": t, "score": scores[i]}
    if cur:
        events.append(cur)
    return events


# --------------------------------------------------------------------------- #
# Per-video / top-level
# --------------------------------------------------------------------------- #
def _event_offsets(n):
    return {1: [0.0], 2: [0.0, 1.0], 3: [-1.0, 0.0, 1.0],
            4: [-1.0, 0.0, 1.0, 2.0]}.get(n, [-2.0, -1.0, 0.0, 1.0, 2.0])[:max(1, n)]


def detect_video(ffmpeg, ffprobe, video, times, profile, out_dir, threshold,
                 frames_per_event, tag, progress, log, should_cancel,
                 base_done, total_units):
    # Each video owns 2*n progress units: the first n cover keyframe extraction,
    # the next n cover template matching — so the bar moves through both phases.
    n0 = len(times)
    nxt = base_done + 2 * n0
    tmp = tempfile.mkdtemp(prefix="notifyshot_")
    saved = []
    try:
        size = video_size(ffprobe, video)
        if not size:
            log(f"⚠ Не удалось прочитать видео: {os.path.basename(video)}")
            return saved, nxt
        roi, tpls = compute_roi_and_templates(profile, *size)

        log(f"Распаковка кадров: {os.path.basename(video)} …")
        pngs = extract_keyframe_crops(
            ffmpeg, video, roi, tmp, should_cancel,
            on_count=lambda c: progress((base_done + min(c, n0)) / total_units))
        if pngs is None:
            return saved, nxt
        n = min(len(pngs), len(times))
        if n == 0:
            return saved, nxt

        log(f"Поиск уведомлений ({n} ключевых кадров) …")
        scores = []
        for i in range(n):
            if should_cancel and should_cancel():
                return saved, nxt
            img = cv2.imread(pngs[i], cv2.IMREAD_GRAYSCALE)
            scores.append(best_score(img, tpls) if img is not None else -1.0)
            if (i & 3) == 0:
                progress((base_done + n0 + i) / total_units)

        events = cluster(times[:n], scores, threshold)
        log(f"Найдено событий: {len(events)} — сохраняю кадры …")
        for k, e in enumerate(events):
            if should_cancel and should_cancel():
                break
            t = e["t"]
            hh = int(t // 3600); mm = int(t % 3600 // 60); ss = t % 60
            offs = _event_offsets(frames_per_event)
            for j, off in enumerate(offs):
                suf = "" if len(offs) == 1 else f"_{j + 1}"
                name = f"{tag}_{k:03d}_{hh:02d}-{mm:02d}-{ss:04.1f}{suf}.png"
                path = os.path.join(out_dir, name)
                extract_full_frame(ffmpeg, video, t + off, path)
                if os.path.isfile(path):
                    saved.append(path)
        return saved, nxt
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(videos, profile, out_dir, sensitivity="med", threshold=None,
        frames_per_event=1, ffmpeg=None, ffprobe=None,
        progress=None, log=None, should_cancel=None):
    """Process all videos. `profile` is a dict (load_profile) or a path."""
    progress = progress or (lambda x: None)
    log = log or (lambda s: None)
    ffmpeg = ffmpeg or find_tool("ffmpeg")
    ffprobe = ffprobe or find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("Не найден ffmpeg/ffprobe. Положите ffmpeg.exe и "
                           "ffprobe.exe в папку «bin» рядом с программой.")
    if isinstance(profile, str):
        profile = load_profile(profile)
    if threshold is None:
        # Each profile may carry its own recommended threshold; the sensitivity
        # preset only nudges it. Falls back to the global "med" value.
        base = profile.get("threshold", SENSITIVITY["med"])
        offset = {"low": -0.07, "med": 0.0, "high": 0.05}.get(sensitivity, 0.0)
        threshold = round(base + offset, 3)
    os.makedirs(out_dir, exist_ok=True)

    progress(-1.0)  # «занят»: анимированная полоса на время анализа
    log("Анализ видео …")
    times_all = [keyframe_times(ffprobe, v) for v in videos]
    total_units = max(1, sum(2 * len(t) for t in times_all))

    base, all_saved = 0, []
    for vi, v in enumerate(videos):
        if should_cancel and should_cancel():
            break
        saved, base = detect_video(
            ffmpeg, ffprobe, v, times_all[vi], profile, out_dir, threshold,
            frames_per_event, f"v{vi + 1}", progress, log, should_cancel,
            base, total_units)
        log(f"✓ {os.path.basename(v)} → {len(saved)} кадр(ов)")
        all_saved += saved
    progress(1.0)
    return all_saved


# --------------------------------------------------------------------------- #
# CLI (testing / tuning)
# --------------------------------------------------------------------------- #
def _scan_report(video, profile_path, topn):
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    profile = load_profile(profile_path)
    times = keyframe_times(ffprobe, video)
    size = video_size(ffprobe, video)
    roi, tpls = compute_roi_and_templates(profile, *size)
    print(f"video={size[0]}x{size[1]}  roi={roi}  tpl={tpls[0].shape[1]}x{tpls[0].shape[0]}")
    tmp = tempfile.mkdtemp(prefix="notifyshot_scan_")
    try:
        pngs = extract_keyframe_crops(ffmpeg, video, roi, tmp, None)
        n = min(len(pngs), len(times))
        sc = np.array([best_score(cv2.imread(pngs[i], cv2.IMREAD_GRAYSCALE), tpls)
                       for i in range(n)])
        print(f"crops={n} max={sc.max():.3f} mean={sc.mean():.3f} | "
              f">=.74:{int((sc>=.74).sum())} >=.82:{int((sc>=.82).sum())} "
              f">=.88:{int((sc>=.88).sum())}")
        for r, i in enumerate(np.argsort(-sc)[:topn]):
            t = times[i]
            print(f"{r:>3}  {int(t//3600):02d}:{int(t%3600//60):02d}:"
                  f"{t%60:05.2f}  {sc[i]:.3f}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    try:                                      # robust Cyrillic/emoji on consoles
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NotifyShot detector (CLI)")
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", default="notifyshot_out")
    ap.add_argument("--sensitivity", choices=list(SENSITIVITY), default="med")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--frames-per-event", type=int, default=1)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--topn", type=int, default=30)
    a = ap.parse_args()

    if a.scan:
        _scan_report(a.videos[0], a.profile, a.topn)
        return

    saved = run(a.videos, a.profile, a.out, sensitivity=a.sensitivity,
                threshold=a.threshold, frames_per_event=a.frames_per_event,
                progress=lambda x: print(f"\r{max(0.0, x)*100:5.1f}%", end="", flush=True),
                log=lambda s: print("\n" + s))
    print(f"\nГотово: сохранено {len(saved)} кадр(ов) в {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
