import tkinter as tk
from tkinter import ttk, messagebox
from entities import Attack, Enemy
from ui_components import ScrollableFrame, fit_window_to_screen
from battle_ui import BattleUI
from battle_logic import BattleLogic
from alliance_ui import AllianceUI
from settings_ui import SettingsUI
from factory import EnemyFactory
from battle_strategies import AggressiveStrategy, DefensiveStrategy, RandomStrategy, SupportStrategy
from battle_map import BattleMapUI


class BattleSimulator(BattleUI, BattleLogic, AllianceUI, SettingsUI, BattleMapUI):
    """Основной класс симулятора битв"""

    def __init__(self, root):
        BattleUI.__init__(self)
        BattleLogic.__init__(self)
        AllianceUI.__init__(self)
        SettingsUI.__init__(self)
        BattleMapUI.__init__(self)

        self.root = root
        self.root.title("Мастер Подземелий - Симулятор Битв")
        fit_window_to_screen(self.root, 1600, 800)
        self.root.minsize(800, 480)

        self.sides = []
        self.num_sides = 2
        self.side_names = ["Сторона А", "Сторона Б", "Сторона В", "Сторона Г", "Сторона Д", "Сторона Е"]
        self.alliance_settings = []
        self.ignore_sides = {}
        self.enemy_types = ["обычный", "гоблин", "орк", "скелет", "тролль", "гном", "эльф", "дротик"]
        self.strategy_types = ["случайная", "агрессивная", "защитная", "поддержка"]
        self.army_frames = []

        self.setup_ui()

    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # ===== Вкладка настройки армий =====
        setup_frame = ttk.Frame(notebook)
        notebook.add(setup_frame, text="Настройка армий")

        setup_scroll_frame = ScrollableFrame(setup_frame)
        setup_scroll_frame.pack(fill='both', expand=True)

        # Кнопки сохранения/загрузки/импорта
        file_frame = ttk.Frame(setup_scroll_frame.scrollable_frame)
        file_frame.pack(fill='x', pady=10)
        ttk.Button(file_frame, text="Сохранить настройки", command=self.save_settings).pack(side='left', padx=5)
        ttk.Button(file_frame, text="Загрузить настройки", command=self.load_settings).pack(side='left', padx=5)
        ttk.Button(file_frame, text="📖 Импортировать из бестиария",
                   command=self.open_bestiary_import).pack(side='left', padx=5)

        # Количество сторон
        ttk.Label(setup_scroll_frame.scrollable_frame, text="Количество сторон:",
                  font=('Arial', 10, 'bold')).pack(anchor='w', pady=10)
        side_frame = ttk.Frame(setup_scroll_frame.scrollable_frame)
        side_frame.pack(fill='x', pady=5)
        self.num_sides_var = tk.IntVar(value=2)
        ttk.Spinbox(side_frame, from_=2, to=6, textvariable=self.num_sides_var, width=10,
                    command=self.update_sides_ui).pack(side='left')

        # Фреймы для настройки сторон
        self.side_frames = []
        self.side_count_vars = []
        self.side_name_vars = []
        sides_container = ttk.Frame(setup_scroll_frame.scrollable_frame)
        sides_container.pack(fill='x', pady=10)

        for i in range(6):
            frame = ttk.LabelFrame(sides_container, text=f"Сторона {chr(65 + i)}")
            frame.grid(row=i // 3, column=i % 3, padx=5, pady=5, sticky='ew')
            self.side_frames.append(frame)

            ttk.Label(frame, text="Название стороны:").grid(row=0, column=0, sticky='w')
            name_var = tk.StringVar(value=f"Сторона {chr(65 + i)}")
            ttk.Entry(frame, textvariable=name_var, width=15).grid(row=0, column=1, padx=5)
            self.side_name_vars.append(name_var)

            ttk.Label(frame, text="Количество врагов:").grid(row=1, column=0, sticky='w', pady=5)
            count_var = tk.IntVar(value=5 if i < 2 else 0)
            ttk.Spinbox(frame, from_=0, to=100, textvariable=count_var, width=10).grid(row=1, column=1, padx=5, pady=5)
            self.side_count_vars.append(count_var)
            frame.grid_remove()

        for i in range(3):
            sides_container.grid_columnconfigure(i, weight=1)

        # Настройка типов армий и тактик
        ttk.Label(setup_scroll_frame.scrollable_frame,
                  text="=== Настройка типов армий и тактик ===",
                  font=('Arial', 12, 'bold')).pack(anchor='w', pady=10)

        types_frame = ttk.Frame(setup_scroll_frame.scrollable_frame)
        types_frame.pack(fill='x', pady=5)

        header_frame = ttk.Frame(types_frame)
        header_frame.grid(row=0, column=0, columnspan=3, sticky='ew', pady=5)
        ttk.Label(header_frame, text="Сторона", font=('Arial', 10, 'bold'), width=15).grid(row=0, column=0, padx=5)
        ttk.Label(header_frame, text="Тип армии", font=('Arial', 10, 'bold'), width=20).grid(row=0, column=1, padx=5)
        ttk.Label(header_frame, text="Тактика", font=('Arial', 10, 'bold'), width=20).grid(row=0, column=2, padx=5)

        self.army_type_vars = []
        self.strategy_type_vars = []

        for i in range(2):
            side_frame = ttk.Frame(types_frame)
            side_frame.grid(row=i + 1, column=0, columnspan=3, sticky='ew', pady=2)

            ttk.Label(side_frame, text=f"Сторона {chr(65 + i)}", width=15).grid(row=0, column=0, padx=5)

            army_type_var = tk.StringVar(value=self.enemy_types[0])
            army_type_combo = ttk.Combobox(side_frame, textvariable=army_type_var,
                                           values=self.enemy_types, width=18, state="readonly")
            army_type_combo.grid(row=0, column=1, padx=5)
            self.army_type_vars.append(army_type_var)

            strategy_type_var = tk.StringVar(value=self.strategy_types[0])
            strategy_type_combo = ttk.Combobox(side_frame, textvariable=strategy_type_var,
                                               values=self.strategy_types, width=18, state="readonly")
            strategy_type_combo.grid(row=0, column=2, padx=5)
            self.strategy_type_vars.append(strategy_type_var)

            self.army_frames.append(side_frame)

        self.types_frame = types_frame
        self.num_sides_var.trace_add("write", lambda *args: self.update_types_ui())

        ttk.Button(setup_scroll_frame.scrollable_frame, text="Создать армии",
                   command=self.create_armies).pack(pady=20)

        # ===== Вкладка битвы =====
        self.battle_frame = ttk.Frame(notebook)
        notebook.add(self.battle_frame, text="Битва")
        self.battle_frame.grid_rowconfigure(0, weight=1)
        self.battle_frame.grid_rowconfigure(1, weight=0)

        # ===== Вкладка альянсов =====
        self.alliance_frame = ttk.Frame(notebook)
        notebook.add(self.alliance_frame, text="Альянсы")

        # ===== Вкладка карты боя =====
        self.map_frame = ttk.Frame(notebook)
        notebook.add(self.map_frame, text="Карта боя")

        # Первоначальное обновление интерфейса
        self.update_sides_ui()

    def open_bestiary_import(self):
        """Открывает окно импорта из бестиария"""
        try:
            from bestiary_importer import BestiaryImporter
        except ImportError:
            messagebox.showerror("Ошибка",
                                 "Файл bestiary_importer.py не найден!\n"
                                 "Убедитесь, что он создан в папке проекта.")
            return

        importer = BestiaryImporter(self.root, self)
        importer.open_import_window()

    def update_sides_ui(self):
        """Обновление отображения сторон в интерфейсе"""
        num_sides = self.num_sides_var.get()
        for i in range(6):
            if i < num_sides:
                self.side_frames[i].grid()
            else:
                self.side_frames[i].grid_remove()

    def update_types_ui(self):
        """Обновление отображения типов армий и тактик при изменении количества сторон"""
        num_sides = self.num_sides_var.get()

        while len(self.army_frames) < num_sides:
            i = len(self.army_frames)
            side_frame = ttk.Frame(self.types_frame)
            side_frame.grid(row=i + 1, column=0, columnspan=3, sticky='ew', pady=2)

            ttk.Label(side_frame, text=f"Сторона {chr(65 + i)}", width=15).grid(row=0, column=0, padx=5)

            army_type_var = tk.StringVar(value=self.enemy_types[0])
            army_type_combo = ttk.Combobox(side_frame, textvariable=army_type_var,
                                           values=self.enemy_types, width=18, state="readonly")
            army_type_combo.grid(row=0, column=1, padx=5)
            self.army_type_vars.append(army_type_var)

            strategy_type_var = tk.StringVar(value=self.strategy_types[0])
            strategy_type_combo = ttk.Combobox(side_frame, textvariable=strategy_type_var,
                                               values=self.strategy_types, width=18, state="readonly")
            strategy_type_combo.grid(row=0, column=2, padx=5)
            self.strategy_type_vars.append(strategy_type_var)

            self.army_frames.append(side_frame)

        for i, frame in enumerate(self.army_frames):
            if i < self.num_sides_var.get():
                frame.grid()
            else:
                frame.grid_remove()

    def create_armies(self):
        """Создание армий на основе текущих настроек"""
        try:
            num_sides = self.num_sides_var.get()
            self.num_sides = num_sides

            self.sides = []
            self.side_names = []

            for i in range(num_sides):
                side_name = self.side_name_vars[i].get()
                enemy_count = self.side_count_vars[i].get()
                army_type = self.army_type_vars[i].get()
                strategy_type = self.strategy_type_vars[i].get()

                self.side_names.append(side_name)
                side_enemies = []

                for j in range(enemy_count):
                    name = f"{side_name}_{j + 1}"
                    enemy = EnemyFactory.create_enemy(army_type, name, i)

                    if strategy_type == "агрессивная":
                        enemy.strategy = AggressiveStrategy()
                    elif strategy_type == "защитная":
                        enemy.strategy = DefensiveStrategy()
                    elif strategy_type == "поддержка":
                        enemy.strategy = SupportStrategy()
                    else:
                        enemy.strategy = RandomStrategy()

                    side_enemies.append(enemy)
                self.sides.append(side_enemies)

            if hasattr(self, 'battle_results_text'):
                delattr(self, 'battle_results_text')

            self.setup_battle_ui()
            self.setup_alliance_ui()

            # Карта боя: новая армия — новая карта
            self.battle_map = None
            self.setup_map_ui()
            self.place_formation()

            messagebox.showinfo("Успех", f"Армии созданы!\nКоличество сторон: {num_sides}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при создании армий: {str(e)}")