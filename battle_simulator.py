import tkinter as tk
from tkinter import ttk, messagebox
from entities import Attack, Enemy
from ui_components import ScrollableFrame, fit_window_to_screen, EditableLabel
from battle_ui import BattleUI
from battle_logic import BattleLogic
from decision_engine import DecisionEngine
from alliance_ui import AllianceUI
from settings_ui import SettingsUI
from factory import EnemyFactory
from battle_strategies import AggressiveStrategy, DefensiveStrategy, RandomStrategy, SupportStrategy
from battle_map import BattleMapUI
from battle_map_model import BattleMap
from theme_manager import ThemeManager, ThemeUI
from side_creator import SideCreatorDialog


class BattleSimulator(BattleUI, BattleLogic, AllianceUI, SettingsUI, BattleMapUI, ThemeUI):
    MAX_SIDES = 26
    """Основной класс симулятора битв"""

    def __init__(self, root):
        engine = DecisionEngine()
        BattleUI.__init__(self, engine)
        BattleLogic.__init__(self, engine)
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
        self.side_army_types = []
        self.side_strategy_vars = []
        self.side_type_labels = []
        self.side_cols = 3
        self.MAX_SIDES = 26

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
        self.num_sides_var = tk.IntVar(value=2)

        # Контейнер карточек сторон (сами карточки создаются по требованию!)
        self.side_frames = []
        self.side_count_vars = []
        self.side_name_vars = []
        sides_container = ttk.Frame(setup_scroll_frame.scrollable_frame)
        sides_container.pack(fill='x', pady=10)
        self.sides_container = sides_container
        for i in range(8):
            sides_container.grid_columnconfigure(i, weight=1 if i < 3 else 0)
        self.side_cols = 3
        sides_container.bind('<Configure>', self.relayout_sides)
        # Круглая кнопка-плюс: добавляет новую сторону в следующий свободный слот
        from ui_components import RoundedButton
        self.add_side_btn = RoundedButton(sides_container, icon='plus',
                                          palette=self.theme_manager.palette(),
                                          command=self.add_side,
                                          width=44, height=44, radius=22,
                                          outline=True, surface_key='bg')

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
            ],
            self.battle_frame: [],
            self.alliance_frame: [],
            self.map_frame: [],
        }

        self._build_nav()
        self.update_sides_layout()

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

    def create_side_card(self, i, army_type, strategy):
        """Карточка стороны: имя-заголовок + состав + тактика + количество + крестик удаления"""
        frame = ttk.LabelFrame(self.sides_container, text="")
        frame.grid(row=i // self.side_cols, column=i % self.side_cols, padx=5, pady=5, sticky='ew')

        name_var = tk.StringVar(value=f"Сторона {self.side_letter(i)}")
        title = EditableLabel(frame, name_var, palette=self.theme_manager.palette())
        title.grid(row=0, column=0, columnspan=2, sticky='w', padx=6, pady=(4, 2))
        cross = ttk.Label(frame, text="✕", cursor="hand2",
                          foreground=self.theme_manager.palette()['fg_muted'],
                          font=('Segoe UI', 10, 'bold'))
        cross.grid(row=0, column=2, padx=(0, 6), pady=(4, 0), sticky='e')
        cross.bind('<Button-1>', lambda e, f=frame, w=cross: self._show_delete_confirm(w, f))
        cross.bind('<Enter>', lambda e, w=cross: w.configure(foreground='#e74c3c'))
        cross.bind('<Leave>', lambda e, w=cross: w.configure(
            foreground=self.theme_manager.palette()['fg_muted']))

        # Состав: read-only лейбл + кнопка смены (индекс ищем по frame в момент клика!)
        ttk.Label(frame, text="Состав:").grid(row=1, column=0, sticky='w', pady=2)
        type_lbl = ttk.Label(frame, text=army_type,
                             foreground=self.theme_manager.palette()['accent'])
        type_lbl.grid(row=1, column=1, sticky='w', padx=5)
        ttk.Button(frame, text="🔄", width=3,
                   command=lambda f=frame: self.change_side_composition(
                       self.side_frames.index(f))).grid(row=1, column=2, padx=2)

        ttk.Label(frame, text="Тактика:").grid(row=2, column=0, sticky='w', pady=2)
        strat_var = tk.StringVar(value=strategy)
        ttk.Combobox(frame, textvariable=strat_var, values=self.strategy_types,
                     width=16, state="readonly").grid(row=2, column=1, padx=5, pady=2)

        ttk.Label(frame, text="Количество врагов:").grid(row=3, column=0, sticky='w', pady=2)
        count_var = tk.IntVar(value=5)
        ttk.Spinbox(frame, from_=0, to=500, textvariable=count_var, width=10).grid(
            row=3, column=1, padx=5, pady=2)

        self.side_frames.append(frame)
        self.side_name_vars.append(name_var)
        self.side_army_types.append(army_type)
        self.side_strategy_vars.append(strat_var)
        self.side_type_labels.append(type_lbl)
        self.side_count_vars.append(count_var)

        for w in (frame, title, title.label, title.entry):
            w.bind("<MouseWheel>", self.setup_scroll_frame._on_mousewheel)

    def change_side_composition(self, i):
        SideCreatorDialog(self, mode='edit', current_type=self.side_army_types[i],
                          on_result=lambda d: self._apply_type(i, d['army_type'], d['strategy']))

    def _create_new_side(self, army_type, strategy, name=None, count=None):
        i = len(self.side_frames)
        self.create_side_card(i, army_type, strategy)
        if name is not None: self.side_name_vars[i].set(name)
        if count is not None: self.side_count_vars[i].set(count)
        self.num_sides_var.set(i + 1)
        self.update_sides_layout()

    def _apply_type(self, i, army_type, strategy):
        self.side_army_types[i] = army_type
        self.side_type_labels[i].configure(text=army_type)
        self.side_strategy_vars[i].set(strategy)

    def launch_bestiary_import(self, on_imported, on_cancel=None):
        """Точка входа для диалога: открывает импортёр и отдаёт ему колбэки успеха/отмены."""
        try:
            from bestiary_importer import BestiaryImporter
        except ImportError:
            messagebox.showerror("Ошибка", "Файл bestiary_importer.py не найден!")
            if on_cancel:
                on_cancel()  # чтобы диалог-родитель не остался спрятанным
            return
        BestiaryImporter(self.root, self,
                         on_imported=on_imported,
                         on_cancel=on_cancel).open_import_window()

    def update_sides_layout(self):
        """Только переставляет существующие карточки + плюсик по текущей сетке."""
        cols = self.side_cols
        n = len(self.side_frames)
        for i, frame in enumerate(self.side_frames):
            frame.grid(row=i // cols, column=i % cols, padx=5, pady=5, sticky='ew')
        if hasattr(self, 'add_side_btn'):
            if n < self.MAX_SIDES:
                self.add_side_btn.grid(row=n // cols, column=n % cols, padx=5, pady=5)
            else:
                self.add_side_btn.grid_remove()

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
                army_type = self.side_army_types[i]
                strategy_type = self.side_strategy_vars[i].get()

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

    def add_side(self):
        SideCreatorDialog(self, mode='create',
                          on_result=lambda d: self._create_new_side(d['army_type'], d['strategy']))

    def _show_delete_confirm(self, anchor_widget, frame):
        """Вскакивающая плашка 'Точно удалить?' прямо поверх карточки (без grab, без Toplevel!)."""
        # Если где-то уже висит открытая плашка - сначала закрываем её
        if getattr(self, '_confirm_popover', None) is not None:
            try:
                self._confirm_popover.destroy()
            except tk.TclError:
                pass
            self._confirm_popover = None

        p = self.theme_manager.palette()
        parent = self.setup_scroll_frame.scrollable_frame   # большой контейнер - плашку не обрежет

        pop = tk.Frame(parent, bg=p['field_bg'], highlightbackground=p['border'],
                       highlightthickness=1)
        tk.Label(pop, text="Удалить отряд?", bg=p['field_bg'], fg=p['fg'],
                 font=('Segoe UI', 9, 'bold')).pack(padx=10, pady=(8, 2))
        btns = tk.Frame(pop, bg=p['field_bg']); btns.pack(pady=(0, 8))

        def close():
            nonlocal pop
            try:
                pop.destroy()
            except tk.TclError:
                pass
            if getattr(self, '_confirm_popover', None) is pop:
                self._confirm_popover = None

        def yes():
            close()
            self.remove_side_by_frame(frame)

        tk.Button(btns, text="✓ Да", command=yes, bd=0, cursor='hand2',
                  bg='#e74c3c', fg='white', activebackground='#c0392b',
                  activeforeground='white', font=('Segoe UI', 8, 'bold'),
                  padx=8, pady=1).pack(side='left', padx=(0, 4))
        tk.Button(btns, text="✕ Нет", command=close, bd=0, cursor='hand2',
                  bg=p['button_bg'], fg=p['button_fg'], activebackground=p['hover'],
                  font=('Segoe UI', 8, 'bold'), padx=8, pady=1).pack(side='left')

        px = anchor_widget.winfo_rootx() + anchor_widget.winfo_width() - parent.winfo_rootx()
        py = anchor_widget.winfo_rooty() + anchor_widget.winfo_height() - parent.winfo_rooty()
        pop.place(x=px, y=py, anchor='ne')
        pop.lift()
        self._confirm_popover = pop

    def remove_side_by_frame(self, frame):
        """Удаляет сторону по объекту карточки: чистит ВСЕ параллельные списки и переставляет сетку."""
        try:
            idx = self.side_frames.index(frame)
        except ValueError:
            return
        frame.destroy()
        for lst in (self.side_frames, self.side_name_vars, self.side_count_vars,
                    self.side_army_types, self.side_strategy_vars, self.side_type_labels):
            del lst[idx]
        # Синхронизируем внутренний счётчик (create_armies читает именно его)
        self.num_sides_var.set(len(self.side_frames))
        self.update_sides_layout()   # плюсик перепрыгнет на освободившееся место

    def relayout_sides(self, event=None):
        """Умная сетка: количество карточек в ряду подстраивается под ширину окна"""
        width = self.sides_container.winfo_width()
        if width < 100:
            return
        cols = max(1, min(8, width // 300))  # одной карточке нужно ~300 px
        if cols == self.side_cols:
            return
        self.side_cols = cols
        for i in range(8):
            self.sides_container.grid_columnconfigure(i, weight=1 if i < cols else 0)
        self.update_sides_layout()