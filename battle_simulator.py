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
from battle_map import BattleMapUI, BattleMap
from theme_manager import ThemeManager, ThemeUI


class BattleSimulator(BattleUI, BattleLogic, AllianceUI, SettingsUI, BattleMapUI, ThemeUI):
    MAX_SIDES = 26
    """Основной класс симулятора битв"""
    def __init__(self, root):
        BattleUI.__init__(self)
        BattleLogic.__init__(self)
        AllianceUI.__init__(self)
        SettingsUI.__init__(self)
        BattleMapUI.__init__(self)
        ThemeUI.__init__(self)

        self.root = root
        self.root.title("Мастер Подземелий - Симулятор Битв")
        self.theme_manager = ThemeManager(root)   #  создаём ДО интерфейса!
        self.theme_manager.apply()                #  красим окно до постройки
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
        # ===== Верхняя панель: навигация по центру, тема справа =====
        p = self.theme_manager.palette()
        self.top_bar = tk.Frame(self.root, bg=p['bg'])
        self.top_bar.pack(fill='x', side='top', pady=(8, 4))
        self.top_bar.grid_columnconfigure(0, weight=1)
        self.top_bar.grid_columnconfigure(2, weight=1)

        self.nav_frame = tk.Frame(self.top_bar, bg=p['bg'])  # центр: кнопки вкладок
        self.nav_frame.grid(row=0, column=1)

        self.theme_holder = tk.Frame(self.top_bar, bg=p['bg'])  # право: кнопка темы
        self.theme_holder.grid(row=0, column=2, sticky='e')
        self.setup_theme_button(self.theme_holder)

        # Нижняя панель: персональные кнопки вкладки
        self.sub_bar = tk.Frame(self.root, bg=p['bg_secondary'])
        self.sub_bar.pack(fill='x', side='bottom')
        self.sub_sep = tk.Frame(self.sub_bar, bg=p['border'], height=2)  # линия-разделитель!
        self.sub_sep.pack(fill='x', side='top')
        self.sub_holder = tk.Frame(self.sub_bar, bg=p['bg_secondary'])
        self.sub_holder.pack(expand=True, pady=6)

        self.tabs_container = ttk.Frame(self.root)
        self.tabs_container.pack(fill='both', expand=True, padx=10, pady=10)

        # Вкладка настройки
        setup_frame = ttk.Frame(self.tabs_container)
        self.setup_frame = setup_frame

        setup_scroll_frame = ScrollableFrame(setup_frame)
        setup_scroll_frame.pack(fill='both', expand=True)
        self.setup_scroll_frame = setup_scroll_frame

        # Количество сторон
        ttk.Label(setup_scroll_frame.scrollable_frame, text="Количество сторон:",
                  font=('Arial', 10, 'bold')).pack(anchor='w', pady=10)
        side_frame = ttk.Frame(setup_scroll_frame.scrollable_frame)
        side_frame.pack(fill='x', pady=5)
        self.num_sides_var = tk.IntVar(value=2)
        ttk.Spinbox(side_frame, from_=2, to=self.MAX_SIDES, textvariable=self.num_sides_var, width=10,
                    command=self.on_num_sides_changed).pack(side='left')

        # Контейнер карточек сторон (сами карточки создаются по требованию!)
        self.side_frames = []
        self.side_count_vars = []
        self.side_name_vars = []
        sides_container = ttk.Frame(setup_scroll_frame.scrollable_frame)
        sides_container.pack(fill='x', pady=10)
        self.sides_container = sides_container
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
        self.num_sides_var.trace_add("write", lambda *args: self.on_num_sides_changed())

        ttk.Button(setup_scroll_frame.scrollable_frame, text="Создать армии",
                   command=self.create_armies).pack(pady=20)

        # Вкладка битвы
        self.battle_frame = ttk.Frame(self.tabs_container)
        self.battle_frame.grid_rowconfigure(0, weight=1)
        self.battle_frame.grid_rowconfigure(1, weight=0)

        # Вкладка альянсов
        self.alliance_frame = ttk.Frame(self.tabs_container)

        # Вкладка карты боя
        self.map_frame = ttk.Frame(self.tabs_container)

        # Список вкладок для переключения круглыми кнопками
        self.tab_frames = [self.setup_frame, self.battle_frame,
                           self.alliance_frame, self.map_frame]
        # Какие кнопки второго яруса принадлежат какой вкладке
        self.tab_sub_buttons = {
            self.setup_frame: [
                ("Сохранить настройки", self.save_settings),
                ("Загрузить настройки", self.load_settings),
                ("Импортировать из бестиария", self.open_bestiary_import),
            ],
            self.battle_frame: [],
            self.alliance_frame: [],
            self.map_frame: [],
        }

        self._build_nav()
        self._build_nav()

        # Первоначальное обновление интерфейса
        self.update_sides_ui()

    def _build_nav(self):
        """Создаёт закруглённые кнопки навигации по центру верхней панели"""
        from ui_components import RoundedButton
        p = self.theme_manager.palette()
        for w in self.nav_frame.winfo_children():
            w.destroy()
        self.nav_buttons = []
        tabs = [("Настройка армий", self.setup_frame),
                ("Битва", self.battle_frame),
                ("Альянсы", self.alliance_frame),
                ("Карта боя", self.map_frame)]
        for text, frame in tabs:
            btn = RoundedButton(self.nav_frame, text, palette=p,
                                command=lambda f=frame: self.select_tab(f),
                                width=150, height=34)
            btn.pack(side='left', padx=4)
            self.nav_buttons.append((btn, frame))
        self.select_tab(self.setup_frame)

    def _build_sub_bar(self, frame):
        """Нижняя панель: контурные кнопки-инструменты выбранной вкладки"""
        from ui_components import RoundedButton
        for w in self.sub_holder.winfo_children():
            w.destroy()
        for text, command in self.tab_sub_buttons.get(frame, []):
            btn = RoundedButton(self.sub_holder, text,
                                palette=self.theme_manager.palette(),
                                command=command,
                                width=180, height=30, radius=10,
                                font=('Segoe UI', 9, 'bold'),
                                outline=True, surface_key='bg_secondary')
            btn.pack(side='left', padx=4)

    def select_tab(self, frame):
        """Переключение вкладки: фрейм, подсветка главной кнопки и кнопки второго яруса"""
        for f in self.tab_frames:
            f.pack_forget()
        frame.pack(fill='both', expand=True)
        for btn, f in self.nav_buttons:
            btn.set_active(f is frame)
        self._build_sub_bar(frame)

    @staticmethod
    def side_letter(i):
        """Имя стороны: A-Z, а дальше цифрами"""
        return chr(65 + i) if i < 26 else str(i + 1)

    def create_side_card(self, i):
        """Создаёт карточку стороны номер i по требованию"""
        frame = ttk.LabelFrame(self.sides_container, text=f"Сторона {self.side_letter(i)}")
        frame.grid(row=i // 3, column=i % 3, padx=5, pady=5, sticky='ew')

        ttk.Label(frame, text="Название стороны:").grid(row=0, column=0, sticky='w')
        name_var = tk.StringVar(value=f"Сторона {self.side_letter(i)}")
        name_entry = ttk.Entry(frame, textvariable=name_var, width=15)
        name_entry.grid(row=0, column=1, padx=5)

        ttk.Label(frame, text="Количество врагов:").grid(row=1, column=0, sticky='w', pady=5)
        count_var = tk.IntVar(value=5 if i < 2 else 0)
        count_spin = ttk.Spinbox(frame, from_=0, to=500, textvariable=count_var, width=10)
        count_spin.grid(row=1, column=1, padx=5, pady=5)

        self.side_frames.append(frame)
        self.side_name_vars.append(name_var)
        self.side_count_vars.append(count_var)

        # Колёсико крутит вкладку, даже когда курсор над карточкой!
        for w in (frame, name_entry, count_spin):
            w.bind("<MouseWheel>", self.setup_scroll_frame._on_mousewheel)

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
        try:
            num_sides = self.num_sides_var.get()
        except (tk.TclError, ValueError):
            return
        while len(self.side_frames) < num_sides:
            self.create_side_card(len(self.side_frames))
        for i, frame in enumerate(self.side_frames):
            if i < num_sides:
                frame.grid()
            else:
                frame.grid_remove()

    def on_num_sides_changed(self):
        try:
            num = self.num_sides_var.get()
        except (tk.TclError, ValueError):
            return
        num = max(2, min(self.MAX_SIDES, num))
        if num != self.num_sides_var.get():
            self.num_sides_var.set(num)
            return
        self.update_sides_ui()
        self.update_types_ui()

    def update_types_ui(self):
        """Обновление отображения типов армий и тактик при изменении количества сторон"""
        num_sides = self.num_sides_var.get()

        while len(self.army_frames) < num_sides:
            i = len(self.army_frames)
            side_frame = ttk.Frame(self.types_frame)
            side_frame.grid(row=i + 1, column=0, columnspan=3, sticky='ew', pady=2)

            ttk.Label(side_frame, text=f"Сторона {self.side_letter(i)}", width=15).grid(row=0, column=0, padx=5)

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

            # Карта боя: новая армия — новая карта (резиновый размер!)
            max_side = max((len(side) for side in self.sides), default=0)
            map_w = max(24, 4 * num_sides)
            zone_cols = max(1, map_w // num_sides)
            map_h = max(16, (max_side + zone_cols - 1) // zone_cols + 2)
            self.battle_map = BattleMap(width=map_w, height=map_h)
            self.setup_map_ui()
            self.place_formation()

            messagebox.showinfo("Успех", f"Армии созданы!\nКоличество сторон: {num_sides}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при создании армий: {str(e)}")