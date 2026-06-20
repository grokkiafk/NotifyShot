#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NotifyShot — нарезка скриншотов из видео по игровому уведомлению.

Интерфейс в стиле лаунчера Majestic: левый сайдбар-навигация + контент,
графитовый фон, фирменный crimson-розовый акцент, безрамочное окно.

Запуск из исходников:  python app.py
Сборка в .exe:         build.bat
"""
import os
import queue
import threading
import tempfile
import webbrowser

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk
from PIL import Image

import detector

if os.name == "nt":
    import ctypes

APP_NAME = "NotifyShot"
VERSION = "v1.0"
GITHUB_URL = "https://github.com/grokkiafk/NotifyShot"
VIDEO_FILETYPES = [("Видео", " ".join("*" + e for e in detector.VIDEO_EXTS)),
                   ("Все файлы", "*.*")]

# --- Палитра, снятая прямо с лаунчера Majestic ------------------------------- #
#   accent #E4185A/#E81C5A · фон #181818 нейтральный · фиолет #9060C6
BG     = "#1A1A1A"   # основной фон (контент)
SIDE   = "#141414"   # сайдбар (чуть темнее)
CARD   = "#222222"   # карточки/строки
CARD2  = "#2A2A2A"   # подсветка строки
FIELD  = "#242424"   # поля ввода/списки
BORDER = "#323232"
PINK   = "#E8195C"   # фирменный crimson-розовый Majestic
PINKH  = "#FF3370"
PURPLE = "#9060C6"   # вторичный акцент (как «Узнать больше»)
FG     = "#F3F3F4"
MUT    = "#8C8C90"
DIM    = "#5C5C60"
OK     = "#34D399"
WARN   = "#FF6B6B"
WHITE  = "#FFFFFF"

ctk.set_appearance_mode("dark")
SENS_LABELS = {"Низкая": "low", "Средняя": "med", "Высокая": "high"}


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
class ProfileMaker(ctk.CTkToplevel):
    MAXW, MAXH = 940, 520

    def __init__(self, master, on_saved):
        super().__init__(master)
        self.title("Новый профиль уведомления")
        self.configure(fg_color=BG)
        self.on_saved = on_saved
        self.resizable(False, False)
        self.after(80, self.grab_set)

        self.img = None
        self.tkimg = None
        self.scale = 1.0
        self.rect = None
        self.start = None

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 4))
        self._ghost(top, "Загрузить картинку…", self.load_image).pack(side="left")
        self._ghost(top, "Взять кадр из видео…", self.frame_from_video).pack(side="left", padx=8)

        ctk.CTkLabel(self, text="Обведите рамкой ПОСТОЯННУЮ часть уведомления "
                     "(иконку и неизменный текст), без меняющихся цифр/ников.",
                     text_color=MUT, anchor="w").pack(fill="x", padx=14)

        self.canvas = tk.Canvas(self, width=self.MAXW, height=self.MAXH,
                                bg=CARD, highlightthickness=0)
        self.canvas.pack(padx=12, pady=8)
        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkLabel(bottom, text="Название:", text_color=FG).pack(side="left")
        self.name_var = tk.StringVar(value="Моё уведомление")
        ctk.CTkEntry(bottom, textvariable=self.name_var, width=220, fg_color=FIELD,
                     border_color=BORDER, text_color=FG).pack(side="left", padx=8)
        ctk.CTkLabel(bottom, text="Порог:", text_color=FG).pack(side="left", padx=(8, 0))
        self.thr_var = tk.StringVar(value="0.88")
        ctk.CTkEntry(bottom, textvariable=self.thr_var, width=64, fg_color=FIELD,
                     border_color=BORDER, text_color=FG).pack(side="left", padx=8)
        self._primary(bottom, "Сохранить профиль", self.save).pack(side="right")

    def _ghost(self, p, text, cmd):
        return ctk.CTkButton(p, text=text, command=cmd, fg_color="transparent",
                             hover_color=FIELD, text_color=FG, border_width=1,
                             border_color=BORDER, corner_radius=8, height=34)

    def _primary(self, p, text, cmd):
        return ctk.CTkButton(p, text=text, command=cmd, fg_color=PINK,
                             hover_color=PINKH, text_color=WHITE, corner_radius=8,
                             height=34, font=ctk.CTkFont(weight="bold"))

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
        ff = detector.find_tool("ffmpeg")
        if not ff:
            messagebox.showerror(APP_NAME, "Не найден ffmpeg.", parent=self)
            return
        tmp = os.path.join(tempfile.gettempdir(), "notifyshot_frame.png")
        detector.extract_full_frame(ff, path, self._parse_time(t), tmp)
        if os.path.isfile(tmp):
            self._set_image(Image.open(tmp).convert("RGB"))  # convert() грузит пиксели
            try:
                os.remove(tmp)                                # за собой не оставляем
            except OSError:
                pass
        else:
            messagebox.showerror(APP_NAME, "Не удалось вытащить кадр "
                                 "(проверьте время).", parent=self)

    @staticmethod
    def _parse_time(s):
        s = s.strip()
        if ":" in s:
            secs = 0.0
            for p in s.split(":"):
                secs = secs * 60 + float(p)
            return secs
        try:
            return float(s)
        except ValueError:
            return 0.0

    def _set_image(self, pil_img):
        from PIL import ImageTk
        self.img = pil_img
        w, h = pil_img.size
        self.scale = min(self.MAXW / w, self.MAXH / h, 1.0)
        disp = pil_img.resize((int(w * self.scale), int(h * self.scale)))
        self.tkimg = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tkimg)
        self.rect = None

    def _down(self, e):
        if self.img is None:
            return
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                                 outline=PINK, width=2)

    def _move(self, e):
        if self.rect:
            self.canvas.coords(self.rect, self.start[0], self.start[1], e.x, e.y)

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
        base, i = slug, 1
        while os.path.exists(os.path.join(d, base + ".json")):
            i += 1
            base = f"{slug}_{i}"
        self.img.crop((bx, by, bx + bw, by + bh)).save(os.path.join(d, base + ".png"))
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
class App(ctk.CTk):
    W, H = 860, 660

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.configure(fg_color=BG)
        self.overrideredirect(True)
        self._center()
        self._ico = os.path.join(detector.resource_dir(), "assets", "notifyshot.ico")
        try:
            if os.path.isfile(self._ico):
                self.iconbitmap(self._ico)
        except Exception:
            pass

        self.f_brand = ctk.CTkFont(family="Segoe UI Black", size=20)
        self.f_nav = ctk.CTkFont(family="Segoe UI Semibold", size=13)
        self.f_sec = ctk.CTkFont(family="Segoe UI Semibold", size=11)
        self.f_btn = ctk.CTkFont(family="Segoe UI Semibold", size=14)

        self.q = queue.Queue()
        self.cancel_evt = threading.Event()
        self.worker = None
        self.profiles = {}
        self.preview_img = None
        self._hwnd = None
        self._busy = False
        self.nav_btns = {}
        self.pages = {}

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_content()
        self._reload_profiles()
        self._check_ffmpeg()
        self._show_page("search")
        self.after(10, self._win_chrome)
        self.after(120, self._poll)

    # ---- безрамочное окно ------------------------------------------------- #
    def _center(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = (sw - self.W) // 2, max(0, (sh - self.H) // 2 - 20)
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _win_chrome(self):
        if os.name != "nt":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            self._hwnd = hwnd
            GWL_EXSTYLE, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = -20, 0x40000, 0x80
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            try:  # иконка в таскбаре
                if os.path.isfile(self._ico):
                    for size, which in ((32, 1), (16, 0)):  # ICON_BIG / ICON_SMALL
                        hicon = ctypes.windll.user32.LoadImageW(
                            None, self._ico, 1, size, size, 0x10)
                        if hicon:
                            ctypes.windll.user32.SendMessageW(hwnd, 0x80, which, hicon)
            except Exception:
                pass
            try:
                pref = ctypes.c_int(2)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
            except Exception:
                pass
            self.withdraw()
            self.after(10, self.deiconify)
        except Exception:
            pass

    def _minimize(self):
        if os.name == "nt" and self._hwnd:
            ctypes.windll.user32.ShowWindow(self._hwnd, 6)
        else:
            self.iconify()

    def _close(self):
        self.cancel_evt.set()
        self.destroy()

    def _start_move(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _do_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _bind_drag(self, *widgets):
        for w in widgets:
            w.bind("<ButtonPress-1>", self._start_move)
            w.bind("<B1-Motion>", self._do_move)

    # ---- сайдбар ---------------------------------------------------------- #
    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=210, fg_color=SIDE, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)

        brand = ctk.CTkFrame(side, fg_color="transparent", height=70)
        brand.pack(fill="x", padx=20, pady=(22, 18))
        b1 = ctk.CTkLabel(brand, text="Notify", text_color=WHITE, font=self.f_brand)
        b1.pack(side="left")
        b2 = ctk.CTkLabel(brand, text="Shot", text_color=PINK, font=self.f_brand)
        b2.pack(side="left")
        self._bind_drag(side, brand, b1, b2)

        for name, label in (("search", "Поиск"), ("profiles", "Профили"),
                            ("settings", "Настройки"), ("about", "О программе")):
            b = ctk.CTkButton(side, text=label, anchor="w", height=42,
                              fg_color="transparent", hover_color="#1F1F1F",
                              text_color=MUT, corner_radius=9, font=self.f_nav,
                              command=lambda n=name: self._show_page(n))
            b.pack(fill="x", padx=12, pady=2)
            self.nav_btns[name] = b

        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=20, pady=16)
        ctk.CTkLabel(bottom, text="для Majestic RP", text_color=DIM,
                     font=ctk.CTkFont(size=11)).pack(anchor="w")
        ctk.CTkLabel(bottom, text=VERSION, text_color=DIM,
                     font=ctk.CTkFont(size=11)).pack(anchor="w")

    def _show_page(self, name):
        for n, b in self.nav_btns.items():
            if n == name:
                b.configure(fg_color="#2A141C", text_color=PINK)
            else:
                b.configure(fg_color="transparent", text_color=MUT)
        for n, p in self.pages.items():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)

    # ---- контент ---------------------------------------------------------- #
    def _build_content(self):
        content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")

        # верхняя полоса с версией и кнопками окна
        bar = ctk.CTkFrame(content, fg_color="transparent", height=40)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self._bind_drag(bar)
        ctk.CTkButton(bar, text="✕", width=44, height=40, corner_radius=0,
                      fg_color="transparent", hover_color=PINK, text_color=MUT,
                      font=ctk.CTkFont(size=15), command=self._close).pack(side="right")
        ctk.CTkButton(bar, text="—", width=44, height=40, corner_radius=0,
                      fg_color="transparent", hover_color=CARD, text_color=MUT,
                      font=ctk.CTkFont(size=15), command=self._minimize).pack(side="right")

        self.holder = ctk.CTkFrame(content, fg_color="transparent")
        self.holder.pack(fill="both", expand=True, padx=22, pady=(0, 18))

        self.pages["search"] = self._page_search()
        self.pages["profiles"] = self._page_profiles()
        self.pages["settings"] = self._page_settings()
        self.pages["about"] = self._page_about()

    def _page(self, title):
        f = ctk.CTkFrame(self.holder, fg_color="transparent")
        ctk.CTkLabel(f, text=title, text_color=WHITE,
                     font=ctk.CTkFont(family="Segoe UI Semibold", size=20),
                     anchor="w").pack(fill="x", pady=(0, 10))
        return f

    def _section(self, parent, text):
        ctk.CTkLabel(parent, text=text.upper(), text_color=MUT, font=self.f_sec,
                     anchor="w").pack(fill="x", pady=(8, 4))

    def _ghost(self, p, text, cmd, width=140, height=32):
        return ctk.CTkButton(p, text=text, command=cmd, width=width, height=height,
                             fg_color="transparent", hover_color=CARD,
                             text_color=FG, border_width=1, border_color=BORDER,
                             corner_radius=8)

    # ---- страница: Поиск -------------------------------------------------- #
    def _page_search(self):
        f = self._page("Поиск уведомлений")

        self._section(f, "Видео")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        listwrap = ctk.CTkFrame(row, fg_color=FIELD, corner_radius=8)
        listwrap.pack(side="left", fill="both", expand=True)
        self.vids = tk.Listbox(listwrap, height=4, activestyle="none", bg=FIELD,
                               fg=FG, selectbackground=PINK, selectforeground=WHITE,
                               highlightthickness=0, borderwidth=0, relief="flat",
                               font=("Segoe UI", 9))
        self.vids.pack(fill="both", expand=True, padx=8, pady=8)
        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", fill="y", padx=(8, 0))
        self._ghost(col, "Добавить видео…", self._add_videos).pack(fill="x")
        self._ghost(col, "Добавить папку…", self._add_folder).pack(fill="x", pady=5)
        sub = ctk.CTkFrame(col, fg_color="transparent")
        sub.pack(fill="x")
        self._ghost(sub, "Убрать", self._remove_sel, width=66).pack(side="left")
        self._ghost(sub, "Очистить", lambda: self.vids.delete(0, "end"),
                    width=66).pack(side="left", padx=(8, 0))

        self._section(f, "Уведомление")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        self.prof_var = tk.StringVar(value="")
        self.prof_menu = ctk.CTkOptionMenu(
            row, variable=self.prof_var, values=[""], width=300,
            command=lambda v: self._update_preview(), fg_color=FIELD,
            button_color=PINK, button_hover_color=PINKH, text_color=FG,
            dropdown_fg_color=CARD, dropdown_hover_color=FIELD,
            dropdown_text_color=FG, corner_radius=8)
        self.prof_menu.pack(side="left")
        self._ghost(row, "Создать новый…", self._new_profile, width=150).pack(side="left", padx=8)
        self.preview = ctk.CTkLabel(f, text="", fg_color="transparent")
        self.preview.pack(anchor="w", pady=(8, 0))

        self._section(f, "Сохранить в")
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        self.out_var = tk.StringVar(value=default_output_dir())
        ctk.CTkEntry(row, textvariable=self.out_var, fg_color=FIELD,
                     border_color=BORDER, text_color=FG, height=34).pack(
                     side="left", fill="x", expand=True)
        self._ghost(row, "Выбрать…", self._pick_out, width=110).pack(side="left", padx=(8, 0))

        run = ctk.CTkFrame(f, fg_color="transparent")
        run.pack(fill="x", pady=(16, 6))
        self.start_btn = ctk.CTkButton(
            run, text="▶   СТАРТ", command=self._start, fg_color=PINK,
            hover_color=PINKH, text_color=WHITE, font=self.f_btn, height=46,
            width=180, corner_radius=10)
        self.start_btn.pack(side="left")
        self.cancel_btn = ctk.CTkButton(
            run, text="Отмена", command=self._cancel, state="disabled",
            fg_color="transparent", hover_color=FIELD, text_color=FG,
            border_width=1, border_color=BORDER, height=46, width=110, corner_radius=10)
        self.cancel_btn.pack(side="left", padx=8)
        self.open_btn = self._ghost(run, "Открыть папку", self._open_out, width=150, height=46)
        self.open_btn.configure(corner_radius=10)
        self.open_btn.pack(side="right")

        self.pbar = ctk.CTkProgressBar(f, progress_color=PINK, fg_color=FIELD,
                                       height=16, corner_radius=8,
                                       indeterminate_speed=1.4)
        self.pbar.set(0)
        self.pbar.pack(fill="x", pady=(8, 4))
        self.status = ctk.CTkLabel(f, text="Готов.", text_color=MUT, anchor="w")
        self.status.pack(fill="x")
        self.log = ctk.CTkTextbox(f, height=84, fg_color=FIELD, text_color=FG,
                                  corner_radius=10, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, pady=(6, 0))
        self.log.configure(state="disabled")
        return f

    # ---- страница: Профили ------------------------------------------------ #
    def _page_profiles(self):
        f = self._page("Профили уведомлений")
        ctk.CTkLabel(f, text="Профиль — это «что искать»: картинка-образец "
                     "уведомления и где оно появляется на экране.",
                     text_color=MUT, anchor="w", justify="left").pack(fill="x", pady=(0, 8))
        ctk.CTkButton(f, text="＋  Создать новый профиль", command=self._new_profile,
                      fg_color=PINK, hover_color=PINKH, text_color=WHITE,
                      font=self.f_btn, height=42, width=240, corner_radius=10,
                      anchor="w").pack(anchor="w", pady=(0, 12))
        self._section(f, "Доступные профили")
        self.prof_list = ctk.CTkScrollableFrame(f, fg_color=FIELD, corner_radius=10)
        self.prof_list.pack(fill="both", expand=True)
        return f

    def _rebuild_profile_list(self):
        if not hasattr(self, "prof_list"):
            return
        for w in self.prof_list.winfo_children():
            w.destroy()
        self._prof_thumbs = []
        import json
        for nm, path in self.profiles.items():
            rowf = ctk.CTkFrame(self.prof_list, fg_color=CARD, corner_radius=8)
            rowf.pack(fill="x", padx=4, pady=4)
            try:
                with open(path, encoding="utf-8") as fh:
                    img = os.path.join(os.path.dirname(path), json.load(fh)["image"])
                im = Image.open(img).convert("RGB"); im.thumbnail((180, 44))
                cim = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
                self._prof_thumbs.append(cim)
                ctk.CTkLabel(rowf, image=cim, text="").pack(side="left", padx=10, pady=8)
            except Exception:
                pass
            ctk.CTkLabel(rowf, text=nm, text_color=FG, anchor="w").pack(
                side="left", padx=6)
            ctk.CTkButton(rowf, text="Выбрать", width=90, height=30, corner_radius=8,
                          fg_color="transparent", hover_color=FIELD, text_color=FG,
                          border_width=1, border_color=BORDER,
                          command=lambda n=nm: self._select_profile(n)).pack(
                          side="right", padx=10)

    def _select_profile(self, name):
        self.prof_var.set(name)
        self._update_preview()
        self._show_page("search")

    # ---- страница: Настройки ---------------------------------------------- #
    def _page_settings(self):
        f = self._page("Настройки")
        ctk.CTkLabel(f, text="По умолчанию подобраны надёжные настройки — "
                     "менять не обязательно.", text_color=MUT, anchor="w").pack(
                     fill="x", pady=(0, 10))

        self._section(f, "Чувствительность")
        self.sens_seg = ctk.CTkSegmentedButton(
            f, values=list(SENS_LABELS), fg_color=FIELD, selected_color=PINK,
            selected_hover_color=PINKH, unselected_color=FIELD,
            unselected_hover_color=BORDER, text_color=FG, height=34)
        self.sens_seg.set("Средняя")
        self.sens_seg.pack(anchor="w")
        ctk.CTkLabel(f, text="Выше — строже (меньше ложных), ниже — больше находит.",
                     text_color=DIM, anchor="w").pack(fill="x", pady=(4, 0))

        self._section(f, "Кадров на событие")
        self.fpe_var = tk.StringVar(value="1")
        ctk.CTkOptionMenu(f, variable=self.fpe_var, values=["1", "2", "3", "4", "5"],
                          width=90, fg_color=FIELD, button_color=PINK,
                          button_hover_color=PINKH, text_color=FG,
                          dropdown_fg_color=CARD, corner_radius=8).pack(anchor="w")

        self._section(f, "Состояние")
        ff = "найден" if detector.find_tool("ffmpeg") else "НЕ найден"
        col = OK if detector.find_tool("ffmpeg") else WARN
        ctk.CTkLabel(f, text=f"ffmpeg: {ff}", text_color=col, anchor="w").pack(fill="x")
        return f

    # ---- страница: О программе -------------------------------------------- #
    def _page_about(self):
        f = self._page("О программе")
        txt = ("NotifyShot автоматически находит повторяющееся игровое "
               "уведомление в длинных записях и сохраняет скриншот на каждое "
               "срабатывание.\n\nРаботает на любом разрешении записи. Под "
               "капотом — ffmpeg и OpenCV.\n\nНеофициальный фан-проект. "
               "Majestic — товарный знак владельцев проекта.")
        ctk.CTkLabel(f, text=txt, text_color=FG, anchor="w", justify="left",
                     wraplength=520).pack(fill="x", pady=(0, 14))
        ctk.CTkButton(f, text="Открыть на GitHub", command=lambda: webbrowser.open(GITHUB_URL),
                      fg_color="transparent", hover_color=CARD, text_color=PURPLE,
                      border_width=1, border_color=BORDER, height=38, width=200,
                      corner_radius=10, anchor="w").pack(anchor="w")
        ctk.CTkLabel(f, text=f"NotifyShot {VERSION} · лицензия MIT",
                     text_color=DIM, anchor="w").pack(fill="x", pady=(14, 0))
        return f

    def _toggle_adv(self):
        self._show_page("settings")

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
        import json
        paths = detector.list_profiles(builtin_templates_dir(), user_templates_dir())
        self.profiles = {}
        for p in paths:
            try:
                with open(p, encoding="utf-8") as f:
                    nm = json.load(f).get("name", os.path.basename(p))
            except Exception:
                nm = os.path.basename(p)
            self.profiles[nm] = p
        names = list(self.profiles) or ["(нет профилей)"]
        self.prof_menu.configure(values=names)
        if self.prof_var.get() not in names:
            self.prof_var.set(names[0])
        self._update_preview()
        self._rebuild_profile_list()

    def _update_preview(self):
        import json
        path = self.profiles.get(self.prof_var.get())
        if not path:
            self.preview.configure(image=None, text="")
            return
        try:
            with open(path, encoding="utf-8") as f:
                img = os.path.join(os.path.dirname(path), json.load(f)["image"])
            im = Image.open(img).convert("RGB")
            im.thumbnail((380, 80))
            self.preview_img = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            self.preview.configure(image=self.preview_img, text="")
        except Exception:
            self.preview.configure(image=None, text="(нет превью)")

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
                             "ffprobe.exe в папку «bin».", WARN)

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
        self._bar_reset()
        self.pbar.set(0)
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self._set_status("Работаю…", FG)

        sens = SENS_LABELS.get(self.sens_seg.get(), "med")
        args = (videos, path, out, sens, int(self.fpe_var.get()))
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

    def _update_progress(self, x):
        if x < 0:                                  # неизвестная длительность
            if not self._busy:
                self._busy = True
                self.pbar.configure(mode="indeterminate")
                self.pbar.start()
            self._set_status("Анализ видео…", FG)
        else:
            if self._busy:
                self._busy = False
                self.pbar.stop()
                self.pbar.configure(mode="determinate")
            self.pbar.set(max(0.0, min(1.0, x)))
            self._set_status(f"Обработка… {int(x * 100)}%", FG)

    def _bar_reset(self):
        if self._busy:
            self.pbar.stop()
            self._busy = False
        self.pbar.configure(mode="determinate")

    def _cancel(self):
        self.cancel_evt.set()
        self._set_status("Останавливаю…", WARN)

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "progress":
                    self._update_progress(payload)
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
        self._bar_reset()
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        if error:
            self._set_status("Ошибка.", WARN)
            messagebox.showerror(APP_NAME, error)
            return
        if self.cancel_evt.is_set():
            self._set_status(f"Остановлено. Сохранено: {len(saved)}.", WARN)
            return
        self.pbar.set(1.0)
        n = len(saved)
        self._set_status(f"Готово! Найдено и сохранено: {n} скрин(ов).", OK)
        if n and messagebox.askyesno(APP_NAME, f"Готово! Сохранено {n} скриншотов.\n"
                                     "Открыть папку с результатами?"):
            self._open_out()

    # ---- мелочи ----------------------------------------------------------- #
    def _set_status(self, text, color=MUT):
        if hasattr(self, "status"):
            self.status.configure(text=text, text_color=color)

    def _log(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_clear(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
