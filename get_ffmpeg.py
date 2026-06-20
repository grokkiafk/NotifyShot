#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Скачивает ffmpeg.exe и ffprobe.exe в папку bin/ (Windows).

Запуск:  python get_ffmpeg.py
Используется при подготовке релиза, чтобы вшить ffmpeg рядом с программой.
"""
import io
import os
import sys
import zipfile
import urllib.request

URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")


def main():
    if os.name != "nt":
        print("Этот скрипт для Windows. На Linux/Mac поставьте ffmpeg пакетом.")
        return
    os.makedirs(BIN, exist_ok=True)
    print(f"Скачиваю ffmpeg…\n{URL}")
    data = urllib.request.urlopen(URL).read()
    print(f"Загружено {len(data) / 1e6:.0f} МБ, распаковываю…")
    got = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            base = os.path.basename(name)
            if base.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                with z.open(name) as src, open(os.path.join(BIN, base), "wb") as dst:
                    dst.write(src.read())
                got += 1
                print("  →", base)
    print("Готово." if got == 2 else f"Внимание: извлечено {got}/2 файлов.")


if __name__ == "__main__":
    main()
