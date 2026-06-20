#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NotifyShot — простое окно для нарезки скриншотов по уведомлению из видео.

Запуск из исходников:  python app.py
Сборка в .exe:         build.bat  (см. README)
"""
import os
import sys
import queue
import threading
import tempfile

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from PIL import Image, ImageTk

import detector

APP_NAME = "NotifyShot"
VIDEO_FILETYPES = [("Видео", " ".join("*" + e for e in detector.VIDEO_EXTS)),
                   ("Все файлы", "*.*")]


def builtin_templates_dir():
    return os.path.join(detector.resource_dir(), "templates")


def user_templates_dir():
    d = os.path.join(detector.app_dir(), "templates")
    os.makedirs(d, exist_ok=True)
    return d


def default_output_dir():
    for base in (os.path.join(os.path.expanduser("~"), "Desktop"),
                 os.path.expanduser("~")):
        if os.path.isdir(base):
            return os.path.join(base, "NotifyShot")
    return os.path.join(os.getcwd(), "NotifyShot")


# =========================================================================== #
#  Мастер создания профиля
# =========================================================================== #
class ProfileMaker(tk.Toplevel):
    """Обведи неизменную часть уведомления на кадре → сохраняется профиль."""
    MAXW, MAXH = 940, 530

    def __init__(self, master, on_saved):
        super().__init__(master)
        self.title("Новый профиль уведомления")
        self.on_saved = on_saved
        self.resizable(False, False)
        self.grab_set()

        self.img = None          # PIL.Image (оригинал)
        self.tkimg = None
        self.scale = 1.0
        self.rect = None
        self.start = None

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="Загрузить картинку…",
                   command=self.load_image).pack(side="left")
        ttk.Button(top, text="Взять кадр из видео…",
                   command=self.frame_from_video).pack(side="left", padx=6)

        ttk.Label(self, foreground="#555", padding=(8, 0),
                  text="Обведите рамкой ПОСТОЯННУЮ часть уведомления "
                       "(иконку и неизменный текст), без меняющихся цифр/ников.").pack(anchor="w")

        self.canvas = tk.Canvas(self, width=self.MAXW, height=self.MAXH,
                                bg="#202024", highlightthickness=0)
        self.canvas.pack(padx=8, pady=6)
        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        ttk.Label(bottom, text="Название:").pack(side="left")
        self.name_var = tk.StringVar(value="Моё уведомление")
        ttk.Entry(bottom, textvariable=self.name_var, width=28).pack(side="left", padx=6)
        ttk.Label(bottom, text="Порог:").pack(side="left", padx=(10, 0))
        self.thr_var = tk.StringVar(value="0.88")
        ttk.Entry(bottom, textvariable=self.thr_var, width=6).pack(side="left", padx=6)
        ttk.Button(bottom, text="Сохранить профиль",
                   command=self.save).pack(side="right")

    # ---- загрузка изображения --------------------------------------------- #
    def load_image(self):
        path = filedialog.askopenfilename(
            parent=self, title="Скриншот с уведомлением",
            filetypes=[("Изображения", "*.png *.jpg *.jpeg *.bmp"), ("Все", "*.*")])
        if path:
            try:
                self._set_image(Image.open(path).convert("RGB"))
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Не удалось открыть: {e}", parent=self)

    def frame_from_video(self):
        path = filedialog.askopenfilename(parent=self, title="Видео",
                                          filetypes=VIDEO_FILETYPES)
        if not path:
            return
        t = simpledialog.askstring(
            "Время кадра", "Время, где видно уведомление (сек или мм:сс):",
            parent=self, initialvalue="60")
        if t is None:
            return
        secs = self._parse_time(t)
        ff = detector.find_tool("ffmpeg")
        if not ff:
            messagebox.showerror(APP_NAME, "Не найден ffmpeg.", parent=self)
            return
        tmp = os.path.join(tempfile.gettempdir(), "notifyshot_frame.png")
        detector.extract_full_frame(ff, path, secs, tmp)
        if os.path.isfile(tmp):
            self._set_image(Image.open(tmp).convert("RGB"))
        else:
            messagebox.showerror(APP_NAME, "Не удалось вытащить кадр "
                                 "(проверьте время).", parent=self)

    @staticmethod
    def _parse_time(s):
        s = s.strip()
        if ":" in s:
            parts = [float(p) for p in s.split(":")]
            secs = 0.0
            for p in parts:
                secs = secs * 60 + p
            return secs
        try:
            return float(s)
        except ValueError:
            return 0.0

    def _set_image(self, pil_img):
        self.img = pil_img
        w, h = pil_img.size
        self.scale = min(self.MAXW / w, self.MAXH / h, 1.0)
        disp = pil_img.resize((int(w * self.scale), int(h * self.scale)))
        self.tkimg = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tkimg)
        self.rect = None

    # ---- рисование рамки -------------------------------------------------- #
    def _down(self, e):
        if self.img is None:
            return
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                                 outline="#37e06a", width=2)

    def _move(self, e):
        if self.rect:
            self.canvas.coords(self.rect, self.start[0], self.start[1], e.x, e.y)

    # ---- сохранение ------------------------------------------------------- #
    def save(self):
        if self.img is None or not self.rect:
            messagebox.showwarning(APP_NAME, "Загрузите кадр и обведите "
                                   "уведомление рамкой.", parent=self)
            return
        x0, y0, x1, y1 = self.canvas.coords(self.rect)
        x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
        bx, by = int(x0 / self.scale), int(y0 / self.scale)
        bw, bh = int((x1 - x0) / self.scale), int((y1 - y0) / self.scale)
        if bw < 8 or bh < 6:
            messagebox.showwarning(APP_NAME, "Рамка слишком маленькая.", parent=self)
            return
        try:
            thr = float(self.thr_var.get().replace(",", "."))
        except ValueError:
            thr = 0.88

        import re, json
        name = self.name_var.get().strip() or "notification"
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower() or "profile"
        d = user_templates_dir()
        base = slug
        i = 1
        while os.path.exists(os.path.join(d, base + ".json")):
            i += 1
            base = f"{slug}_{i}"
        crop = self.img.crop((bx, by, bx + bw, by + bh))
        crop.save(os.path.join(d, base + ".png"))
        prof = {"name": name, "image": base + ".png",
                "box": [bx, by, bw, bh], "src_size": list(self.img.size),
                "pad": [1.5, 5.0, 1.5], "threshold": round(thr, 3)}
        with open(os.path.join(d, base + ".json"), "w", encoding="utf-8") as f:
            json.dump(prof, f, ensure_ascii=False, indent=2)
        messagebox.showinfo(APP_NAME, f"Профиль «{name}» сохранён.", parent=self)
        self.on_saved(os.path.join(d, base + ".json"))
        self.destroy()


# =========================================================================== #
#  Главное окно
# =========================================================================== #
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME + " — скриншоты по уведомлению")
        self.geometry("720x640")
        self.minsize(680, 600)

        self.q = queue.Queue()
        self.cancel_evt = threading.Event()
        self.worker = None
        self.profiles = {}          # name -> path
        self.preview_img = None

        self._build()
        self._reload_profiles()
        self._check_ffmpeg()
        self.after(100, self._poll)

    # ---- интерфейс -------------------------------------------------------- #
    def _build(self):
        pad = dict(padx=10, pady=(6, 0))

        # видео
        f1 = ttk.LabelFrame(self, text=" 1. Видео ")
        f1.pack(fill="both", **pad)
        self.vids = tk.Listbox(f1, height=5, activestyle="none")
        self.vids.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        b = ttk.Frame(f1); b.pack(side="left", fill="y", padx=6, pady=6)
        ttk.Button(b, text="Добавить видео…", command=self._add_videos).pack(fill="x")
        ttk.Button(b, text="Добавить папку…", command=self._add_folder).pack(fill="x", pady=4)
        ttk.Button(b, text="Убрать", command=self._remove_sel).pack(fill="x")
        ttk.Button(b, text="Очистить", command=lambda: self.vids.delete(0, "end")).pack(fill="x", pady=4)

        # профиль
        f2 = ttk.LabelFrame(self, text=" 2. Что искать ")
        f2.pack(fill="x", **pad)
        row = ttk.Frame(f2); row.pack(fill="x", padx=6, pady=6)
        self.prof_var = tk.StringVar()
        self.prof_cb = ttk.Combobox(row, textvariable=self.prof_var,
                                    state="readonly", width=40)
        self.prof_cb.pack(side="left")
        self.prof_cb.bind("<<ComboboxSelected>>", lambda e: self._update_preview())
        ttk.Button(row, text="Создать новый…", command=self._new_profile).pack(side="left", padx=6)
        ttk.Button(row, text="⟳", width=3, command=self._reload_profiles).pack(side="left")
        self.preview = ttk.Label(f2)
        self.preview.pack(anchor="w", padx=8, pady=(0, 6))

        # вывод
        f3 = ttk.LabelFrame(self, text=" 3. Куда сохранять ")
        f3.pack(fill="x", **pad)
        row = ttk.Frame(f3); row.pack(fill="x", padx=6, pady=6)
        self.out_var = tk.StringVar(value=default_output_dir())
        ttk.Entry(row, textvariable=self.out_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Выбрать…", command=self._pick_out).pack(side="left", padx=6)

        # настройки
        f4 = ttk.LabelFrame(self, text=" 4. Настройки ")
        f4.pack(fill="x", **pad)
        row = ttk.Frame(f4); row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="Чувствительность:").pack(side="left")
        self.sens = tk.StringVar(value="med")
        for txt, val in (("Низкая", "low"), ("Средняя", "med"), ("Высокая", "high")):
            ttk.Radiobutton(row, text=txt, value=val, variable=self.sens).pack(side="left", padx=4)
        ttk.Label(row, text="     Кадров на событие:").pack(side="left")
        self.fpe = tk.IntVar(value=1)
        ttk.Spinbox(row, from_=1, to=5, width=4, textvariable=self.fpe).pack(side="left", padx=4)

        # запуск
        f5 = ttk.Frame(self); f5.pack(fill="x", padx=10, pady=8)
        self.start_btn = ttk.Button(f5, text="▶  СТАРТ", command=self._start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(f5, text="Отмена", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.open_btn = ttk.Button(f5, text="Открыть папку", command=self._open_out)
        self.open_btn.pack(side="right")

        self.pbar = ttk.Progressbar(self, mode="determinate", maximum=1000)
        self.pbar.pack(fill="x", padx=10)
        self.status = ttk.Label(self, text="Готов.", foreground="#444")
        self.status.pack(anchor="w", padx=10, pady=(2, 0))

        self.log = tk.Text(self, height=9, wrap="word", state="disabled",
                           bg="#fbfbfb", relief="solid", borderwidth=1)
        self.log.pack(fill="both", expand=True, padx=10, pady=8)

    # ---- видео ------------------------------------------------------------ #
    def _add_videos(self):
        for p in filedialog.askopenfilenames(title="Выберите видео",
                                              filetypes=VIDEO_FILETYPES):
            self.vids.insert("end", p)

    def _add_folder(self):
        d = filedialog.askdirectory(title="Папка с видео")
        if not d:
            return
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(detector.VIDEO_EXTS):
                self.vids.insert("end", os.path.join(d, fn))

    def _remove_sel(self):
        for i in reversed(self.vids.curselection()):
            self.vids.delete(i)

    # ---- профили ---------------------------------------------------------- #
    def _reload_profiles(self):
        paths = detector.list_profiles(builtin_templates_dir(), user_templates_dir())
        self.profiles = {}
        for p in paths:
            try:
                import json
                with open(p, encoding="utf-8") as f:
                    nm = json.load(f).get("name", os.path.basename(p))
            except Exception:
                nm = os.path.basename(p)
            self.profiles[nm] = p
        names = list(self.profiles)
        self.prof_cb["values"] = names
        if names and self.prof_var.get() not in names:
            self.prof_var.set(names[0])
        self._update_preview()

    def _update_preview(self):
        path = self.profiles.get(self.prof_var.get())
        if not path:
            self.preview.config(image="", text="")
            return
        try:
            import json
            with open(path, encoding="utf-8") as f:
                img = os.path.join(os.path.dirname(path), json.load(f)["image"])
            im = Image.open(img).convert("RGB")
            im.thumbnail((360, 80))
            self.preview_img = ImageTk.PhotoImage(im)
            self.preview.config(image=self.preview_img, text="")
        except Exception:
            self.preview.config(image="", text="(нет превью)")

    def _new_profile(self):
        ProfileMaker(self, on_saved=lambda path: (self._reload_profiles(),
                     self.prof_var.set(self._name_for(path)), self._update_preview()))

    def _name_for(self, path):
        for nm, p in self.profiles.items():
            if p == path:
                return nm
        return self.prof_var.get()

    # ---- вывод ------------------------------------------------------------ #
    def _pick_out(self):
        d = filedialog.askdirectory(title="Куда сохранять скриншоты")
        if d:
            self.out_var.set(d)

    def _open_out(self):
        d = self.out_var.get()
        if os.path.isdir(d):
            try:
                os.startfile(d)
            except Exception:
                pass
        else:
            messagebox.showinfo(APP_NAME, "Папка ещё не создана.")

    # ---- ffmpeg ----------------------------------------------------------- #
    def _check_ffmpeg(self):
        if not (detector.find_tool("ffmpeg") and detector.find_tool("ffprobe")):
            self._set_status("⚠ ffmpeg не найден — положите ffmpeg.exe и "
                             "ffprobe.exe в папку «bin».", "#b00")

    # ---- запуск/поток ----------------------------------------------------- #
    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        videos = list(self.vids.get(0, "end"))
        if not videos:
            messagebox.showwarning(APP_NAME, "Добавьте хотя бы одно видео.")
            return
        path = self.profiles.get(self.prof_var.get())
        if not path:
            messagebox.showwarning(APP_NAME, "Выберите профиль уведомления.")
            return
        out = self.out_var.get().strip()
        if not out:
            messagebox.showwarning(APP_NAME, "Укажите папку для сохранения.")
            return

        self._log_clear()
        self.cancel_evt.clear()
        self.pbar["value"] = 0
        self.start_btn["state"] = "disabled"
        self.cancel_btn["state"] = "normal"
        self._set_status("Работаю…", "#444")

        args = (videos, path, out, self.sens.get(), int(self.fpe.get()))
        self.worker = threading.Thread(target=self._work, args=args, daemon=True)
        self.worker.start()

    def _work(self, videos, profile, out, sens, fpe):
        try:
            saved = detector.run(
                videos, profile, out, sensitivity=sens, frames_per_event=fpe,
                progress=lambda x: self.q.put(("progress", x)),
                log=lambda s: self.q.put(("log", s)),
                should_cancel=self.cancel_evt.is_set)
            self.q.put(("done", saved))
        except Exception as e:
            self.q.put(("error", str(e)))

    def _cancel(self):
        self.cancel_evt.set()
        self._set_status("Останавливаю…", "#b00")

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "progress":
                    self.pbar["value"] = max(0, min(1000, int(payload * 1000)))
                elif kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self._finish(payload)
                elif kind == "error":
                    self._finish(None, error=payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self, saved, error=None):
        self.start_btn["state"] = "normal"
        self.cancel_btn["state"] = "disabled"
        if error:
            self._set_status("Ошибка.", "#b00")
            messagebox.showerror(APP_NAME, error)
            return
        if self.cancel_evt.is_set():
            self._set_status(f"Остановлено. Сохранено: {len(saved)}.", "#b00")
            return
        self.pbar["value"] = 1000
        n = len(saved)
        self._set_status(f"Готово! Найдено и сохранено: {n} скрин(ов).", "#0a0")
        if n and messagebox.askyesno(APP_NAME, f"Готово! Сохранено {n} скриншотов.\n"
                                     "Открыть папку с результатами?"):
            self._open_out()

    # ---- мелочи ----------------------------------------------------------- #
    def _set_status(self, text, color="#444"):
        self.status.config(text=text, foreground=color)

    def _log(self, s):
        self.log["state"] = "normal"
        self.log.insert("end", s.rstrip() + "\n")
        self.log.see("end")
        self.log["state"] = "disabled"

    def _log_clear(self):
        self.log["state"] = "normal"
        self.log.delete("1.0", "end")
        self.log["state"] = "disabled"


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
