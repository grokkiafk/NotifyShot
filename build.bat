@echo off
REM ---------------------------------------------------------------------------
REM  Сборка NotifyShot в один .exe (Windows).
REM  Требуется: Python 3.10+, затем:  pip install -r requirements.txt pyinstaller
REM  ffmpeg.exe / ffprobe.exe положите в папку bin\ ПЕРЕД сборкой релиза,
REM  чтобы они попали рядом с готовым exe (см. get_ffmpeg.py).
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where pyinstaller >nul 2>nul || (
  echo [NotifyShot] PyInstaller не найден. Устанавливаю...
  python -m pip install pyinstaller || goto :err
)

echo [NotifyShot] Сборка...
pyinstaller --noconfirm --onefile --windowed --name NotifyShot ^
  --icon "assets\notifyshot.ico" ^
  --add-data "templates;templates" ^
  --add-data "assets\notifyshot.ico;assets" ^
  --collect-all customtkinter ^
  --collect-all darkdetect ^
  app.py || goto :err

REM Положим ffmpeg рядом с exe, если он есть в bin\
if exist "bin\ffmpeg.exe"  copy /y "bin\ffmpeg.exe"  "dist\bin\ffmpeg.exe"  >nul 2>nul
if exist "bin\ffprobe.exe" copy /y "bin\ffprobe.exe" "dist\bin\ffprobe.exe" >nul 2>nul
if exist "bin\ffmpeg.exe" (
  if not exist "dist\bin" mkdir "dist\bin"
  copy /y "bin\ffmpeg.exe"  "dist\bin\ffmpeg.exe"  >nul
  copy /y "bin\ffprobe.exe" "dist\bin\ffprobe.exe" >nul
)

echo.
echo [NotifyShot] Готово:  dist\NotifyShot.exe
echo   Для раздачи: заархивируйте папку dist целиком (exe + bin\ffmpeg).
goto :eof

:err
echo [NotifyShot] ОШИБКА сборки.
exit /b 1
