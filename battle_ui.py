import tkinter as tk
from tkinter import ttk, messagebox

from combat_core import CRIT_MODE_LABELS, normalize_crit_mode
from entities import Attack, Enemy
from ui_components import ScrollableFrame, fit_window_to_screen
from observer import Observer



class UIUpdater(Observer):
    def __init__(self, battle_ui):
        self.battle_ui = battle_ui

    def update(self, subject):
        bu = self.battle_ui
        if not hasattr(bu, '_dirty_enemies'):
            bu._dirty_enemies = set()
        bu._dirty_enemies.add(subject)
        if getattr(bu, 'ui_suspend', False):
            return
        if hasattr(bu, 'update_battle_ui'):
            bu.update_battle_ui()


class BattleUI:
    """Класс для управления интерфейсом битвы"""

    def __init__(self, engine):
        """Инициализация UI обновителя."""
        self.engine = engine
        self._dirty_enemies = set()
        self.label_by_enemy = {}
        self.ui_suspend = False
        self.crit_damage_mode = 'double_all'

    def setup_battle_ui(self):
        """Настройка интерфейса битвы"""
        # Создаем UIUpdater здесь, а не в __init__, чтобы гарантировать его наличие
        if not hasattr(self, 'ui_updater'):
            self.ui_updater = UIUpdater(self)

        # Полностью очищаем battle frame
        for widget in self.battle_frame.winfo_children():
            widget.destroy()

        self.label_by_enemy = {}

        # Создаем основной контейнер с прокруткой
        main_scroll_frame = ScrollableFrame(self.battle_frame)
        main_scroll_frame.pack(fill='both', expand=True)

        # Создание фреймов для каждой стороны с прокруткой
        self.side_vars = []
        self.side_frames_battle = []
        enemy_frames_container = ttk.Frame(main_scroll_frame.scrollable_frame)
        enemy_frames_container.pack(fill='x', pady=(0, 10))

        # Расчет количества колонок на основе количества сторон
        num_columns = min(self.num_sides, 3)  # Максимум 3 колонки

        # Привязываем наблюдатель к каждому врагу
        for side_enemies in self.sides:
            for enemy in side_enemies:
                enemy.attach(self.ui_updater)

        for i, (side_enemies, side_name) in enumerate(zip(self.sides, self.side_names)):
            side_container = ttk.LabelFrame(enemy_frames_container, text=side_name)
            side_container.grid(row=i // num_columns, column=i % num_columns, padx=5, pady=5, sticky='nsew')

            # Создание прокручиваемого фрейма
            scroll_frame = ScrollableFrame(side_container)
            scroll_frame.pack(fill='both', expand=True)

            side_vars = []
            select_all_var = tk.BooleanVar()

            # Чекбокс "Выделить все"
            select_frame = ttk.Frame(scroll_frame.scrollable_frame)
            select_frame.pack(fill='x', pady=5)
            ttk.Checkbutton(select_frame, text="Выделить все", variable=select_all_var,
                            command=lambda idx=i: self.toggle_select_all(idx)).pack(side='left')

            for j, enemy in enumerate(side_enemies):
                var = tk.BooleanVar()
                frame = ttk.Frame(scroll_frame.scrollable_frame)
                frame.pack(fill='x', pady=2)
                ttk.Checkbutton(frame, variable=var).pack(side='left')
                status = "🟢" if enemy.alive else "🔴"
                attack_info = ", ".join([f"{a.name}+{a.attack_bonus}" for a in enemy.attacks])
                lbl = ttk.Label(frame, text=f"{status} {enemy.name}: {enemy.hp}/{enemy.max_hp} HP [{attack_info}]")
                lbl.pack(side='left')
                self.label_by_enemy[enemy] = lbl  # прямая ссылка: обновление за O(1)!
                for w in (frame, lbl):
                    w.bind('<Double-Button-1>', lambda e, en=enemy: self.edit_enemy(en))
                side_vars.append(var)

            self.side_vars.append(side_vars)
            self.side_frames_battle.append((scroll_frame, select_all_var))

        # Настройка сетки контейнера врагов
        for i in range(num_columns):
            enemy_frames_container.grid_columnconfigure(i, weight=1)

        # Секция результатов
        results_label = ttk.Label(main_scroll_frame.scrollable_frame, text="Результаты боя:",
                                  font=('Arial', 10, 'bold'))
        results_label.pack(anchor='w', pady=(10, 5))

        # Создание текстового виджета для результатов с прокруткой
        results_container = ttk.Frame(main_scroll_frame.scrollable_frame)
        results_container.pack(fill='both', expand=True, pady=(0, 10))

        self.battle_results_text = tk.Text(results_container, height=15, width=100)
        results_scrollbar = ttk.Scrollbar(results_container, orient="vertical", command=self.battle_results_text.yview)
        self.battle_results_text.configure(yscrollcommand=results_scrollbar.set)

        self.battle_results_text.pack(side='left', fill='both', expand=True)
        results_scrollbar.pack(side='right', fill='y')
        self.battle_results_text.bind('<KeyPress>', self._on_results_keypress, add='+')

        # Управление битвой
        controls_frame = ttk.Frame(self.battle_frame)
        controls_frame.pack(fill='x', pady=10)

        # Центрирование кнопок
        button_container = ttk.Frame(controls_frame)
        button_container.pack(expand=True)

        ttk.Button(button_container, text="Провести раунд боя", command=self.run_battle_round).pack(side='left', padx=5)
        ttk.Button(button_container, text="Массовое редактирование", command=self.mass_edit).pack(side='left', padx=5)
        ttk.Button(button_container, text="Показать статус", command=self.show_status).pack(side='left', padx=5)
        ttk.Button(button_container, text="Очистить результаты", command=self.clear_results).pack(side='left', padx=5)
        self.copy_btn = ttk.Button(button_container, text="📋 Копировать лог",
                                   command=self.copy_results)
        self.copy_btn.pack(side='left', padx=5)
        ttk.Button(button_container, text="🔍 Анализ сражения",
                   command=self.open_decision_analysis).pack(side='left', padx=5)
        mode = normalize_crit_mode(getattr(self, 'crit_damage_mode', 'double_all'))
        self.crit_damage_mode = mode
        self.crit_mode_var = tk.StringVar(value=CRIT_MODE_LABELS[mode])
        ttk.Label(button_container, text='Крит:').pack(side='left', padx=(12, 2))
        crit_box = ttk.Combobox(button_container, textvariable=self.crit_mode_var,
                                values=list(CRIT_MODE_LABELS.values()),
                                state='readonly', width=26)
        crit_box.pack(side='left', padx=4)

        def _sync_crit(_event=None):
            self.crit_damage_mode = normalize_crit_mode(self.crit_mode_var.get())

        crit_box.bind('<<ComboboxSelected>>', _sync_crit)

    def _select_all_results(self, event=None):
        w = self.battle_results_text
        w.tag_remove('sel', '1.0', 'end')
        w.tag_add('sel', '1.0', 'end-1c')
        return 'break'

    def _on_results_keypress(self, event):
        # Раскладочно-независимый якорь: keycode = VK-код клавиши на Windows,
        # НЕ зависит от раскладки/кодировки (в отличие от keysym, который на
        # кириллице приходит как не-ASCII и в консоли печатается '??').
        # Ctrl+C -> VK_C=67 всегда; Ctrl+A -> VK_A=65.
        ctrl = bool(event.state & 0x0004)
        kc = event.keycode
        if ctrl:
            if kc == 67:  # VK_C: Ctrl+C на любой раскладке
                self.battle_results_text.after(0, self.copy_results)
                return 'break'  # break ДО update() -> class-binding не спит
            if kc == 65:  # VK_A: Ctrl+A
                self.battle_results_text.after(0, self._select_all_results)
                return 'break'
            if kc in (37, 39, 38, 40, 36, 35, 33, 34):  # стрелки/Home/End/PgUp/PgDn (VK)
                return None  # Ctrl+навигация - пропускаем
            return 'break'  # Ctrl+V/X/Z и пр. - блок (read-only)
        if kc in (8, 46):  # VK_BACK=8, VK_DELETE=46
            return 'break'  # удаление - блок
        ch = event.char
        if ch and ch.isprintable():
            return 'break'  # ввод текста - блок
        return None

    def copy_results(self):
        w = self.battle_results_text
        try:
            sel = w.get('sel.first', 'sel.last')  # TclError, если выделения нет
        except tk.TclError:
            sel = ''
        text = sel if sel else w.get('1.0', 'end-1c')  # fallback: весь лог

        # Единственный рабочий канал: Tk clipboard + форс синхронизации.
        # (txt-fallback убран: keycode-доказательство подтвердило, что clipboard
        # доходит до Windows штатно, страховка от msy2-поломки стала лишней.)
        try:
            w.clipboard_clear()
            w.clipboard_append(text)
            w.update()  # обрабатываем очередь событий -> ownership уходит в Windows
        except tk.TclError:
            pass

        # Тихий визуальный отклик кнопки (НЕ окно). Единственный сигнал успеха
        # после удаления messagebox.showinfo - поэтому оставляем намеренно.
        if hasattr(self, 'copy_btn'):
            try:
                self.copy_btn.configure(text='✓ Скопировано')
                self.copy_btn.after(1200, lambda: self.copy_btn.configure(text='📋 Копировать лог'))
            except tk.TclError:
                pass

    def open_decision_analysis(self):
        """Окно объяснимости СПР: почему каждый юнит выбрал именно это действие.
        Читает immutable-снимки ENGINE.get_round_log() (НЕ пересчёт - мир изменился).
        Свёрнутые карточки-аккордеоны на юнита, на чистом ttk -> цвета подхватывают
        активную тему (тёмно-фиолетовая схема) без хардкода. Graceful: нет раундов ->
        заглушка, не краш."""
        log = self.engine.get_round_log()
        win = tk.Toplevel(self.root)
        win.title("Анализ сражения — почему принято каждое решение")
        fit_window_to_screen(win, 720, 640)

        outer = ttk.Frame(win); outer.pack(fill='both', expand=True, padx=10, pady=10)
        if not log:
            ttk.Label(outer, text="Раундов ещё не проводилось — проведите бой и откройте анализ.",
                      font=('Segoe UI', 11)).pack(pady=20)
            return
        ttk.Label(outer, text=f"Решений за последний раунд: {len(log)}",
                  font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 6))

        canvas = tk.Canvas(outer)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        body.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for snap in log:
            self._decision_card(body, snap)

    def _decision_card(self, parent, s):
        """Одна сворачиваемая карточка юнита (паттерн аккордеона, как в editor)."""
        wrap = ttk.Frame(parent, relief='groove', borderwidth=1)
        wrap.pack(fill='x', pady=3, padx=2)
        head = ttk.Frame(wrap); head.pack(fill='x')
        arrow = ttk.Label(head, text='▸', width=2, cursor='hand2', font=('Segoe UI', 10, 'bold'))
        arrow.pack(side='left')
        int_txt = 'не указан' if s['int_score'] is None else str(s['int_score'])
        title = f"{s['unit']}  ·  INT={int_txt} → Tier {s['tier']} ({s['tier_name']})  ·  {s['archetype']}"
        ttk.Label(head, text=title, font=('Segoe UI', 10, 'bold'), cursor='hand2').pack(side='left', fill='x', expand=True)
        detail = ttk.Frame(wrap)

        st = {'open': False, 'body': detail, 'arrow': arrow}
        def toggle(_e=None):
            if st['open']:
                st['body'].pack_forget(); st['arrow'].configure(text='▸'); st['open'] = False
            else:
                st['body'].pack(fill='x', padx=8, pady=(0, 4)); st['arrow'].configure(text='▾'); st['open'] = True
        for w in (head, arrow):
            w.bind('<Button-1>', toggle)
        head.bind('<Button-1>', toggle)

        # --- содержимое карточки ---
        rows = [
            ('🎯 Цель', f"{s['target_name'] or '—'}  ·  {s['target_reason']}"),
            ('⚔️ Атака', (f"{s['attack_name'] or 'мультиатака/делегат'}  ·  {s['attack_reason']}")
                          if not s['multiattack'] else s['attack_reason']),
            ('👣 Движение', f"{s['move_intent']}  ·  {s['move_reason']}"),
        ]
        for label, val in rows:
            ttk.Label(detail, text=label, font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(4, 0))
            ttk.Label(detail, text=val, font=('Segoe UI', 9), wraplength=640, justify='left').pack(anchor='w')
        # таблица кандидатов (сердце "почему именно эта атака")
        if s['candidates']:
            ttk.Label(detail, text='📋 Разбор оружия (B1 дальность / B2 защиты / B3 EV):',
                      font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(6, 2))
            grid = ttk.Frame(detail); grid.pack(fill='x')
            for col, txt in enumerate(('Атака', 'Reach', 'Тип', 'Eff', 'EV', 'Вердикт')):
                ttk.Label(grid, text=txt, font=('Segoe UI', 8, 'bold')).grid(
                    row=0, column=col, sticky='w', padx=4)
            for i, cd in enumerate(s['candidates'], start=1):
                verdict = '✔ выбрана' if cd.get('chosen') else (cd['reject'] or 'проиграла по EV/reach')
                for col, val in enumerate((cd['name'], cd['reach'], cd['dmg_type'],
                                           cd['eff'], cd['ev'], verdict)):
                    ttk.Label(grid, text=str(val), font=('Segoe UI', 8)).grid(
                        row=i, column=col, sticky='w', padx=4)

    def clear_results(self):
        """Очистка текстового поля с результатами"""
        if hasattr(self, 'battle_results_text'):
            self.battle_results_text.delete(1.0, tk.END)

    def toggle_select_all(self, side_idx):
        """Выделение/снятие выделения всех врагов на стороне"""
        select_all_var = self.side_frames_battle[side_idx][1]
        for var in self.side_vars[side_idx]:
            var.set(select_all_var.get())

    def mass_edit(self):
        """Массовое редактирование выбранных врагов"""
        selected_enemies = []
        for i, side_vars in enumerate(self.side_vars):
            for j, var in enumerate(side_vars):
                if var.get():
                    selected_enemies.append(self.sides[i][j])

        if not selected_enemies:
            messagebox.showwarning("Внимание", "Выберите хотя бы одного врага для редактирования!")
            return

        # Открытие диалога массового редактирования
        self.open_mass_edit_dialog(selected_enemies)

    def open_mass_edit_dialog(self, enemies):
        """Открытие окна массового редактирования"""
        edit_window = tk.Toplevel(self.root)
        edit_window.title("Массовое редактирование")
        fit_window_to_screen(edit_window, 600, 800)
        edit_window.minsize(400, 300)

        # Создание прокручиваемого фрейма для диалога
        main_frame = ttk.Frame(edit_window)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        canvas = tk.Canvas(main_frame)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Привязка прокрутки колесом мыши
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        scrollable_frame.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side='right', fill='y')

        ttk.Label(scrollable_frame, text=f"Редактирование {len(enemies)} врагов",
                  font=('Arial', 12, 'bold')).pack(pady=10)

        # Основная информация
        ttk.Label(scrollable_frame, text="Основные параметры:", font=('Arial', 10, 'bold')).pack(anchor='w', pady=5)

        ttk.Label(scrollable_frame, text="Имя:").pack(anchor='w', pady=2)
        name_var = tk.StringVar(value=enemies[0].name)
        ttk.Entry(scrollable_frame, textvariable=name_var, width=30).pack(pady=2)

        ttk.Label(scrollable_frame, text="Здоровье:").pack(anchor='w', pady=2)
        hp_var = tk.IntVar(value=enemies[0].hp)
        ttk.Spinbox(scrollable_frame, from_=1, to=500, textvariable=hp_var, width=10).pack(pady=2)

        ttk.Label(scrollable_frame, text="Класс доспеха:").pack(anchor='w', pady=2)
        ac_var = tk.IntVar(value=enemies[0].ac)
        ttk.Spinbox(scrollable_frame, from_=1, to=30, textvariable=ac_var, width=10).pack(pady=2)

        # Секция атак
        ttk.Label(scrollable_frame, text="Атаки:", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(10, 5))

        # Фрейм для списка атак
        attacks_frame = ttk.Frame(scrollable_frame)
        attacks_frame.pack(fill='x', pady=5)

        # Listbox для атак
        ttk.Label(attacks_frame, text="Список атак:").pack(anchor='w')
        attacks_listbox = tk.Listbox(attacks_frame, height=4)
        attacks_listbox.pack(fill='x', pady=5)

        # Кнопки для управления атаками
        attack_buttons_frame = ttk.Frame(attacks_frame)
        attack_buttons_frame.pack(fill='x', pady=5)

        ttk.Button(attack_buttons_frame, text="Добавить атаку",
                   command=lambda: self.add_attack_to_listbox(attacks_listbox, enemies)).pack(side='left', padx=2)
        ttk.Button(attack_buttons_frame, text="Удалить атаку",
                   command=lambda: self.remove_attack_from_listbox(attacks_listbox, enemies)).pack(side='left', padx=2)
        ttk.Button(attack_buttons_frame, text="Редактировать атаку",
                   command=lambda: self.edit_attack_in_listbox(attacks_listbox, enemies)).pack(side='left', padx=2)

        # Заполнение listbox атаками
        self.update_attacks_listbox(attacks_listbox, enemies[0])

        def save_changes():
            """Сохранение изменений для всех выбранных врагов"""
            for enemy in enemies:
                enemy.name = name_var.get()
                enemy.hp = hp_var.get()
                enemy.max_hp = hp_var.get()
                enemy.ac = ac_var.get()
                enemy.alive = enemy.hp > 0

            edit_window.destroy()
            self.setup_battle_ui()
            messagebox.showinfo("Успех", f"Параметры {len(enemies)} врагов обновлены!")

        # Кнопка сохранения внизу
        ttk.Button(scrollable_frame, text="Сохранить", command=save_changes).pack(pady=20)

        # Сохранение ссылок для доступа в методах
        self.current_edit_enemies = enemies
        self.current_attacks_listbox = attacks_listbox

    def update_attacks_listbox(self, listbox, enemy):
        """Обновление списка атак в listbox"""
        listbox.delete(0, tk.END)
        for attack in enemy.attacks:
            listbox.insert(tk.END,
                           f"{attack.name} (+{attack.attack_bonus}, {attack.damage_dice_count}{attack.damage_dice_type}+{attack.damage_modifier})")

    def add_attack_to_listbox(self, listbox, enemies):
        """Добавление новой атаки выбранным врагам"""
        # Используем данные из первого врага для предзаполнения
        sample_enemy = enemies[0]

        attack_dialog = tk.Toplevel(self.root)
        attack_dialog.title("Добавить атаку")
        fit_window_to_screen(attack_dialog, 400, 500)

        ttk.Label(attack_dialog, text="Новая атака", font=('Arial', 12, 'bold')).pack(pady=10)

        ttk.Label(attack_dialog, text="Название атаки:").pack(pady=2)
        name_var = tk.StringVar(value="Новая атака")
        ttk.Entry(attack_dialog, textvariable=name_var, width=30).pack(pady=2)

        ttk.Label(attack_dialog, text="Бонус к атаке:").pack(pady=2)
        bonus_var = tk.IntVar(value=0)
        ttk.Spinbox(attack_dialog, from_=-10, to=20, textvariable=bonus_var, width=10).pack(pady=2)

        ttk.Label(attack_dialog, text="Кол-во костей:").pack(pady=2)
        dice_count_var = tk.IntVar(value=1)
        ttk.Spinbox(attack_dialog, from_=1, to=20, textvariable=dice_count_var, width=10).pack(pady=2)

        ttk.Label(attack_dialog, text="Тип кости:").pack(pady=2)
        dice_type_var = tk.StringVar(value="d6")
        ttk.Combobox(attack_dialog, values=["d4", "d6", "d8", "d10", "d12"],
                     textvariable=dice_type_var, width=10).pack(pady=2)

        ttk.Label(attack_dialog, text="Модификатор:").pack(pady=2)
        mod_var = tk.IntVar(value=0)
        ttk.Spinbox(attack_dialog, from_=-10, to=20, textvariable=mod_var, width=10).pack(pady=2)

        ttk.Label(attack_dialog, text="Тип урона:").pack(pady=2)
        damage_type_var = tk.StringVar(value="")
        ttk.Entry(attack_dialog, textvariable=damage_type_var, width=20).pack(pady=2)

        def add_attack():
            """Создание новой атаки и добавление ее всем выбранным врагам"""
            new_attack = Attack(
                name_var.get(),
                bonus_var.get(),
                dice_count_var.get(),
                dice_type_var.get(),
                mod_var.get(),
                damage_type_var.get()
            )

            for enemy in enemies:
                enemy.attacks.append(new_attack)

            # Обновляем listbox, используя первого врага
            self.update_attacks_listbox(listbox, enemies[0])
            attack_dialog.destroy()

        ttk.Button(attack_dialog, text="Добавить", command=add_attack).pack(pady=20)

    def remove_attack_from_listbox(self, listbox, enemies):
        """Удаление выбранной атаки у всех выбранных врагов"""
        selection = listbox.curselection()
        if selection:
            index = selection[0]
            for enemy in enemies:
                if index < len(enemy.attacks):
                    enemy.attacks.pop(index)
            self.update_attacks_listbox(listbox, enemies[0])
        else:
            messagebox.showwarning("Внимание", "Выберите атаку для удаления!")

    def edit_attack_in_listbox(self, listbox, enemies):
        """Редактирование выбранной атаки у всех выбранных врагов"""
        selection = listbox.curselection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите атаку для редактирования!")
            return

        index = selection[0]
        attack_sample = enemies[0].attacks[index]  # Используем первый для UI

        # Создаем окно редактирования
        attack_dialog = tk.Toplevel(self.root)
        attack_dialog.title("Редактировать атаку")
        fit_window_to_screen(attack_dialog, 400, 500)

        ttk.Label(attack_dialog, text="Редактирование атаки", font=('Arial', 12, 'bold')).pack(pady=10)

        name_var = tk.StringVar(value=attack_sample.name)
        ttk.Entry(attack_dialog, textvariable=name_var, width=30).pack(pady=2)

        bonus_var = tk.IntVar(value=attack_sample.attack_bonus)
        ttk.Spinbox(attack_dialog, from_=-10, to=20, textvariable=bonus_var, width=10).pack(pady=2)

        dice_count_var = tk.IntVar(value=attack_sample.damage_dice_count)
        ttk.Spinbox(attack_dialog, from_=1, to=20, textvariable=dice_count_var, width=10).pack(pady=2)

        dice_type_var = tk.StringVar(value=attack_sample.damage_dice_type)
        ttk.Combobox(attack_dialog, values=["d4", "d6", "d8", "d10", "d12"],
                     textvariable=dice_type_var, width=10).pack(pady=2)

        mod_var = tk.IntVar(value=attack_sample.damage_modifier)
        ttk.Spinbox(attack_dialog, from_=-10, to=20, textvariable=mod_var, width=10).pack(pady=2)

        damage_type_var = tk.StringVar(value=attack_sample.damage_type)
        ttk.Entry(attack_dialog, textvariable=damage_type_var, width=20).pack(pady=2)

        def save_attack():
            """Сохранение изменений атаки для всех выбранных врагов"""
            for enemy in enemies:
                attack = enemy.attacks[index]
                attack.name = name_var.get()
                attack.attack_bonus = bonus_var.get()
                attack.damage_dice_count = dice_count_var.get()
                attack.damage_dice_type = dice_type_var.get()
                attack.damage_modifier = mod_var.get()
                attack.damage_type = damage_type_var.get()

            self.update_attacks_listbox(listbox, enemies[0])
            attack_dialog.destroy()

        ttk.Button(attack_dialog, text="Сохранить", command=save_attack).pack(pady=20)

    def edit_enemy(self, enemy):
        """Редактирование одного врага"""
        self.open_mass_edit_dialog([enemy])

    def show_status(self):
        """Показать текущий статус всех врагов"""
        status_text = "=== ТЕКУЩИЙ СТАТУС ===\n"
        for i, (side_enemies, side_name) in enumerate(zip(self.sides, self.side_names)):
            status_text += f"{side_name}:\n"
            for enemy in side_enemies:
                status = "🟢 ЖИВ" if enemy.alive else "🔴 МЕРТВ"
                ignore_text = f" (Игнорирует: {', '.join([self.side_names[s] for s in enemy.ignore_sides])})" if enemy.ignore_sides else ""
                attacks_text = ", ".join([f"{attack.name}+{attack.attack_bonus}" for attack in enemy.attacks])
                status_text += f"  {enemy.name}: {enemy.hp}/{enemy.max_hp} HP [{attacks_text}] ({status}){ignore_text}\n"
            status_text += "\n"

        if hasattr(self, 'battle_results_text'):
            self.battle_results_text.insert(tk.END, status_text + "\n")
            self.battle_results_text.see(tk.END)

    def update_battle_ui(self):
        """Обновление интерфейса: только изменившиеся враги, O(число изменений)"""
        dirty = getattr(self, '_dirty_enemies', set())
        for enemy in dirty:
            label = self.label_by_enemy.get(enemy)
            if label is None:
                continue
            status = "🟢" if enemy.alive else "🔴"
            attack_info = ", ".join([f"{a.name}+{a.attack_bonus}" for a in enemy.attacks])
            label.configure(text=f"{status} {enemy.name}: {enemy.hp}/{enemy.max_hp} HP [{attack_info}]")
        dirty.clear()