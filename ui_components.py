import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    """Прокручиваемый фрейм для создания скроллинга в интерфейсе"""

    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # Привязка прокрутки колесом мыши
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.scrollable_frame.bind("<MouseWheel>", self._on_mousewheel)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _on_mousewheel(self, event):
        """Обработчик прокрутки колесом мыши"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


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