Сюда нужно положить ffmpeg.exe и ffprobe.exe.

Способ 1 (автоматически):
    python get_ffmpeg.py

Способ 2 (вручную):
    Скачайте сборку с https://www.gyan.dev/ffmpeg/builds/
    (ffmpeg-release-essentials.zip), и скопируйте из неё
    bin\ffmpeg.exe и bin\ffprobe.exe в эту папку.

Эти файлы НЕ хранятся в git (см. .gitignore) — они большие.
В готовом релизе папка bin\ лежит рядом с NotifyShot.exe.
