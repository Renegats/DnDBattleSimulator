import tkinter as tk
from tkinter import ttk
import math

class ScrollableFrame(ttk.Frame):
    """Прокручиваемый фрейм: контент растянут на всю ширину canvas"""

    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        # Запоминаем id окна, чтобы управлять его шириной!
        self.window_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # ГЛАВНАЯ МАГИЯ: при изменении размера canvas растягиваем контент на всю ширину
        self.canvas.bind('<Configure>', self._on_canvas_configure)

        # Привязка прокрутки колесом мыши
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.scrollable_frame.bind("<MouseWheel>", self._on_mousewheel)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _on_canvas_configure(self, event):
        """Контент всегда шириной с видимую область canvas"""
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel(self, event):
        """Обработчик прокрутки колесом мыши"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

class EditableLabel(ttk.Frame):
    """Заголовок, который становится полем ввода по клику.
    Label и Entry привязаны к одному StringVar"""

    def __init__(self, master, textvariable, palette=None,
                 font=('Segoe UI', 10, 'bold')):
        super().__init__(master)
        self.var = textvariable
        self.palette = palette or {}
        self.font = font
        self._hover = False

        # Label = обычный вид заголовка
        self.label = ttk.Label(self, textvariable=self.var, font=font, cursor='hand2')
        self.label.pack(anchor='w')
        self.label.bind('<Button-1>', self._start_edit)
        self.label.bind('<Enter>', self._on_enter)
        self.label.bind('<Leave>', self._on_leave)

        # Entry = режим редактирования (скрыт до клика)
        self.entry = ttk.Entry(self, textvariable=self.var, font=font, width=18)
        self.entry.bind('<Return>', self._stop_edit)        # Enter = сохранить
        self.entry.bind('<KP_Enter>', self._stop_edit)
        self.entry.bind('<FocusOut>', self._stop_edit)      # клик мимо = сохранить
        self.entry.bind('<Escape>', lambda e: self._stop_edit())

        self._apply_colors()

    # переключение режимов
    def _start_edit(self, event=None):
        self.label.pack_forget()
        self.entry.pack(anchor='w', fill='x')
        self.entry.focus_set()
        self.entry.select_range(0, 'end')   #

    def _stop_edit(self, event=None):
        self.entry.pack_forget()
        self.label.pack(anchor='w')
        self._apply_colors()                # вернуть заголовку обычный цвет

    def _on_enter(self, event=None):
        self._hover = True
        self.label.configure(foreground=self.palette.get('accent', '#5865f2'))

    def _on_leave(self, event=None):
        self._hover = False
        self.label.configure(foreground=self.palette.get('fg', '#000000'))

    def _apply_colors(self):
        fg = self.palette.get('accent' if self._hover else 'fg', '#000000')
        self.label.configure(foreground=fg, background=self.palette.get('bg', '#ffffff'))
        self.entry.configure(background=self.palette.get('field_bg', '#ffffff'))

    def apply_palette(self, palette):
        """Перекраска под новую тему (вызывается из _retint_all)"""
        self.palette = palette
        self._apply_colors()

def fit_window_to_screen(window, desired_width, desired_height):
    """Устанавливает размер окна, не превышающий экран, и центрирует его"""
    window.update_idletasks()
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()

    # Оставляем поля для панели задач и рамок окна
    max_w = max(400, screen_w - 60)
    max_h = max(300, screen_h - 100)

    w = min(desired_width, max_w)
    h = min(desired_height, max_h)

    x = max(0, (screen_w - w) // 2)
    y = max(0, (screen_h - h) // 2)

    window.geometry(f"{w}x{h}+{x}+{y}")

class RoundedButton(tk.Canvas):
    """Закруглённая кнопка: hover-подсветка, тема, иконки, контурный режим"""

    def __init__(self, master, text='', command=None, palette=None,
                 width=150, height=34, radius=12, font=('Segoe UI', 10, 'bold'),
                 icon=None, outline=False, surface_key=None):
        super().__init__(master, width=width, height=height,
                         highlightthickness=0, bd=0, cursor='hand2')
        self.text = text
        self.icon = icon
        self.command = command
        self.width = width
        self.height = height
        self.radius = radius
        self.font = font
        self.palette = palette or {}
        self.outline = outline          # контурный стиль для второстепенных кнопок
        self.surface_key = surface_key  # ключ палитры поверхности, на которой лежит кнопка
        self.hover = False
        self.active = False
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<Button-1>', self._on_click)
        self.redraw()

    def apply_palette(self, palette):
        self.palette = palette
        self.redraw()

    def set_active(self, state):
        self.active = state
        self.redraw()

    def set_text(self, text):
        self.text = text
        self.redraw()

    def set_icon(self, icon):
        self.icon = icon
        self.redraw()

    def _on_enter(self, e):
        self.hover = True
        self.redraw()

    def _on_leave(self, e):
        self.hover = False
        self.redraw()

    def _on_click(self, e):
        if self.command:
            self.command()

    def _base(self):
        """Цвет поверхности под кнопкой (фон панели)"""
        if self.surface_key:
            return self.palette.get(self.surface_key, self.palette.get('bg', '#ffffff'))
        return self.palette.get('bg', '#ffffff')

    def _colors(self):
        p = self.palette
        if self.active:
            return p.get('accent', '#5865f2'), '#ffffff'
        if self.hover:
            return p.get('hover', p.get('button_bg', '#cccccc')), p.get('fg', '#000000')
        if self.outline:
            return self._base(), p.get('fg_muted', p.get('fg', '#000000'))
        return p.get('bg_secondary', '#eeeeee'), p.get('fg', '#000000')

    def _round_shape(self, x0, y0, x1, y1, r, fill):
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline='')
        self.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, outline='')
        self.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, fill=fill, outline='')
        self.create_oval(x1 - 2 * r, y0, x1, y0 + 2 * r, fill=fill, outline='')
        self.create_oval(x0, y1 - 2 * r, x0 + 2 * r, y1, fill=fill, outline='')
        self.create_oval(x1 - 2 * r, y1 - 2 * r, x1, y1, fill=fill, outline='')

    def redraw(self):
        self.delete('all')
        self.configure(bg=self._base())
        fill, fg = self._colors()
        x0, y0, x1, y1 = 1, 1, self.width - 1, self.height - 1
        r = min(self.radius, (min(self.width, self.height) - 2) / 2)
        if self.outline:
            # Контурная кнопка: рамочка + прозрачное тело, сливающееся с панелью
            ring = (self.palette.get('accent', '#5865f2') if (self.hover or self.active)
                    else self.palette.get('border', '#999999'))
            self._round_shape(x0, y0, x1, y1, r, ring)
            self._round_shape(x0 + 1.5, y0 + 1.5, x1 - 1.5, y1 - 1.5, max(1, r - 2), fill)
        else:
            self._round_shape(x0, y0, x1, y1, r, fill)
        if self.icon:
            self._draw_icon(fill)
        elif self.text:
            self.create_text(self.width / 2, self.height / 2, text=self.text,
                             fill=fg, font=self.font)

    def _draw_icon(self, fill):
        """Рисует солнце, луну или плюс строго по центру"""
        import math
        p = self.palette
        cx, cy = self.width / 2, self.height / 2
        r = min(self.width, self.height) / 2 - 8
        if self.icon == 'moon':
            color = p.get('icon_moon', '#f5d76e')
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline='')
            self.create_oval(cx - r + r * 0.7, cy - r - r * 0.35,
                             cx + r + r * 0.7, cy + r - r * 0.35, fill=fill, outline='')
        elif self.icon == 'sun':
            color = p.get('icon_sun', '#e8a33d')
            core = r * 0.55
            self.create_oval(cx - core, cy - core, cx + core, cy + core, fill=color, outline='')
            for i in range(8):
                ang = i * math.pi / 4
                self.create_line(cx + math.cos(ang) * r * 0.75, cy + math.sin(ang) * r * 0.75,
                                 cx + math.cos(ang) * r, cy + math.sin(ang) * r,
                                 fill=color, width=2)
        elif self.icon == 'plus':
            # Плюс в кружочке: при наведении всё вспыхивает акцентом!
            color = (p.get('accent', '#5865f2') if (self.hover or self.active)
                     else p.get('fg_muted', '#888888'))
            rr = min(self.width, self.height) / 2 - 7
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                             outline=color, width=2, fill='')
            arm = rr * 0.55
            self.create_line(cx - arm, cy, cx + arm, cy, fill=color, width=2)
            self.create_line(cx, cy - arm, cx, cy + arm, fill=color, width=2)