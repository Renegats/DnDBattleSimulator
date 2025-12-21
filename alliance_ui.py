import tkinter as tk
from tkinter import ttk, messagebox
from ui_components import ScrollableFrame


class AllianceUI:
    """Класс для управления интерфейсом альянсов"""

    def __init__(self):
        """Инициализация UI альянсов"""
        pass

    def setup_alliance_ui(self):
        """Настройка интерфейса для управления альянсами"""
        # Очистка фрейма альянсов
        for widget in self.alliance_frame.winfo_children():
            widget.destroy()

        if self.num_sides <= 2:
            ttk.Label(self.alliance_frame, text="Для настройки альянсов требуется минимум 3 стороны",
                      font=('Arial', 12)).pack(pady=50)
            return

        # Создание прокручиваемого фрейма для альянсов
        alliance_scroll_frame = ScrollableFrame(self.alliance_frame)
        alliance_scroll_frame.pack(fill='both', expand=True)

        ttk.Label(alliance_scroll_frame.scrollable_frame,
                  text="Настройка альянсов - выберите, какие стороны игнорируют друг друга",
                  font=('Arial', 12, 'bold')).pack(pady=10)

        # Создание матрицы альянсов
        alliance_frame = ttk.Frame(alliance_scroll_frame.scrollable_frame)
        alliance_frame.pack(pady=20)

        # Заголовок строки
        for i in range(self.num_sides):
            ttk.Label(alliance_frame, text=self.side_names[i], font=('Arial', 10, 'bold')).grid(row=0, column=i + 1,
                                                                                                padx=10, pady=5)

        # Матрица альянсов
        self.alliance_vars = []
        for i in range(self.num_sides):
            row_vars = []
            ttk.Label(alliance_frame, text=self.side_names[i], font=('Arial', 10, 'bold')).grid(row=i + 1, column=0,
                                                                                                padx=10, pady=5)
            for j in range(self.num_sides):
                if i == j:
                    ttk.Label(alliance_frame, text="-").grid(row=i + 1, column=j + 1, padx=5, pady=2)
                    row_vars.append(None)
                else:
                    var = tk.BooleanVar()
                    # Восстановление предыдущих настроек альянсов если они существуют
                    if hasattr(self, 'alliance_settings') and self.alliance_settings:
                        if i < len(self.alliance_settings) and j < len(self.alliance_settings[i]):
                            var.set(self.alliance_settings[i][j])
                    cb = ttk.Checkbutton(alliance_frame, variable=var)
                    cb.grid(row=i + 1, column=j + 1, padx=5, pady=2)
                    row_vars.append(var)
            self.alliance_vars.append(row_vars)

        ttk.Button(alliance_scroll_frame.scrollable_frame, text="Применить настройки альянсов",
                   command=self.apply_alliances).pack(pady=20)

    def apply_alliances(self):
        """Применение настроек альянсов к врагам"""
        # Сохранение настроек альянсов
        self.alliance_settings = []
        self.ignore_sides = {}  # Сброс глобальных настроек

        for i in range(self.num_sides):
            row_settings = []
            ignore_set = set()
            for j in range(self.num_sides):
                if i == j:
                    row_settings.append(False)
                else:
                    is_ignored = self.alliance_vars[i][j].get()
                    row_settings.append(is_ignored)
                    if is_ignored:
                        ignore_set.add(j)
            self.alliance_settings.append(row_settings)
            self.ignore_sides[i] = ignore_set

        # Сброс всех списков игнорирования у врагов
        for side in self.sides:
            for enemy in side:
                enemy.ignore_sides.clear()

        # Применение новых альянсов к врагам
        for i in range(self.num_sides):
            for j in self.ignore_sides.get(i, set()):
                for enemy in self.sides[i]:
                    enemy.ignore_sides.add(j)

        messagebox.showinfo("Успех", "Настройки альянсов применены!")