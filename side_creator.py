import tkinter as tk
from tkinter import ttk, messagebox
from ui_components import RoundedButton, ScrollableFrame, fit_window_to_screen
from factory import EnemyFactory
from characteristics_editor import CharacteristicsEditor


class SideCreatorDialog:
    """Модальное окно 'кого создать': импорт из бестиария или свой существ."""

    def __init__(self, simulator, mode='create', current_type=None, on_result=None):
        self.sim = simulator
        self.mode = mode                      # 'create' | 'edit'
        self.current_type = current_type
        self.on_result = on_result or (lambda d: None)
        self.pal = simulator.theme_manager.palette()
        self.attacks = []
        self.multiattack_data = None
        self.chars_data = {}
        self.win = tk.Toplevel(simulator.root)
        self.win.title("Кого ведём в бой?" if mode == 'create' else "Изменить состав")
        self.win.transient(simulator.root)
        fit_window_to_screen(self.win, 560, 480)
        self._build_choice_screen()

    # экран выбора пути
    def _build_choice_screen(self):
        for w in self.win.winfo_children():
            w.destroy()
        p = self.pal
        pad = ttk.Frame(self.win); pad.pack(fill='both', expand=True, padx=14, pady=12)

        ttk.Label(pad, text="Тактика отряда:", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        self.strat_var = tk.StringVar(value=self.sim.strategy_types[0])
        ttk.Combobox(pad, textvariable=self.strat_var, values=self.sim.strategy_types,
                     width=16, state='readonly').pack(anchor='w', pady=(0, 10))

        ttk.Label(pad, text="Выберите, откуда взять существ:",
                  font=('Segoe UI', 10)).pack(anchor='w', pady=(4, 8))

        row = ttk.Frame(pad); row.pack(fill='x')
        RoundedButton(row, "📖  Импорт из бестиария\n(тянем статблок с dnd.su)",
                      palette=p, command=self._start_import,
                      width=250, height=70, radius=14, font=('Segoe UI', 10, 'bold'))\
            .pack(side='left', padx=4)
        RoundedButton(row, "🛠  Свой существ\n(характеристики вручную)",
                      palette=p, command=self._build_custom_form,
                      width=250, height=70, radius=14, font=('Segoe UI', 10, 'bold'))\
            .pack(side='left', padx=4)

        if self.mode == 'edit':
            ttk.Label(pad, text=f"Текущий состав: {self.current_type}",
                      font=('Segoe UI', 9, 'italic')).pack(anchor='w', pady=(10, 0))

    # путь: импорт
    def _start_import(self):
        self.win.withdraw()

        def done(type_name):
            self.win.destroy()
            self.on_result({'army_type': type_name, 'strategy': self.strat_var.get()})

        def cancel():
            self.win.deiconify()

        self.sim.launch_bestiary_import(on_imported=done, on_cancel=cancel)

    # путь: кастом
    def _build_custom_form(self):
        for w in self.win.winfo_children():
            w.destroy()
        sf = ScrollableFrame(self.win)
        sf.pack(fill='both', expand=True, padx=10, pady=10)
        f = sf.scrollable_frame

        ttk.Label(f, text="Пресет (встроенный тип):", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        pr = ttk.Frame(f); pr.pack(fill='x', pady=(0, 8))
        self.preset_var = tk.StringVar(value=self.sim.enemy_types[0])
        ttk.Combobox(pr, textvariable=self.preset_var, values=self.sim.enemy_types,
                     width=16, state='readonly').pack(side='left')
        ttk.Button(pr, text="Загрузить пресет в поля", command=self._load_preset).pack(side='left', padx=6)

        self.name_var = tk.StringVar(value="")
        self.hp_var = tk.IntVar(value=10)
        self.ac_var = tk.IntVar(value=10)
        self.spd_var = tk.IntVar(value=30)
        self.regen_var = tk.IntVar(value=0)
        for label, var, rng in (("Имя существа:", self.name_var, None),
                                ("Хиты:", self.hp_var, (1, 1000)),
                                ("Класс доспеха:", self.ac_var, (1, 30)),
                                ("Скорость (фт):", self.spd_var, (0, 200)),
                                ("Регенерация:", self.regen_var, (0, 100))):
            ttk.Label(f, text=label).pack(anchor='w', pady=(4, 0))
            if rng:
                ttk.Spinbox(f, from_=rng[0], to=rng[1], textvariable=var, width=12).pack(anchor='w')
            else:
                ttk.Entry(f, textvariable=var, width=24).pack(anchor='w')

        ttk.Label(f, text="Атаки:", font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 2))
        self.atk_box = tk.Listbox(f, height=4); self.atk_box.pack(fill='x')
        btns = ttk.Frame(f); btns.pack(fill='x', pady=4)
        ttk.Button(btns, text="＋ атака", command=self._add_attack).pack(side='left', padx=2)
        ttk.Button(btns, text="✎ изменить", command=self._edit_attack).pack(side='left', padx=2)
        ttk.Button(btns, text="✕ удалить", command=self._del_attack).pack(side='left', padx=2)
        self._refresh_atk_box()
        self._refresh_atk_box()

        self.editor = CharacteristicsEditor(f, initial=self.chars_data, palette=self.pal)

        bottom = ttk.Frame(f); bottom.pack(fill='x', pady=12)

        bottom = ttk.Frame(f); bottom.pack(fill='x', pady=12)
        RoundedButton(bottom, "Отмена", palette=self.pal, command=self.win.destroy,
                      width=120, height=32, radius=10, outline=True).pack(side='left', padx=4)
        RoundedButton(bottom, "✅ Создать сторону", palette=self.pal, command=self._confirm_custom,
                      width=170, height=32, radius=10).pack(side='left', padx=4)

    def _load_preset(self):
        tmp = EnemyFactory.create_enemy(self.preset_var.get(), "_preset_", 0)
        self.multiattack_data = getattr(tmp, 'multiattack', None)
        self.chars_data = {
            'ability_scores': dict(getattr(tmp, 'ability_scores', {}) or {}),
            'ability_mods':   dict(getattr(tmp, 'ability_mods', {}) or {}),
            'saves':          dict(getattr(tmp, 'saves', {}) or {}),
            'skills':         dict(getattr(tmp, 'skills', {}) or {}),
            'senses':         dict(getattr(tmp, 'senses', {}) or {}),
            'vulnerabilities':list(getattr(tmp, 'vulnerabilities', []) or []),
            'resistances':    list(getattr(tmp, 'resistances', []) or []),
            'immunities':     list(getattr(tmp, 'immunities', []) or []),
            'condition_immunities': list(getattr(tmp, 'condition_immunities', []) or []),
            'languages':      list(getattr(tmp, 'languages', []) or []),
            'cr':             getattr(tmp, 'cr', None),
            'prof_bonus':     getattr(tmp, 'prof_bonus', None),
            'size':           getattr(tmp, 'size', None),
            'type':           getattr(tmp, 'type', None),
            'traits':         [dict(tr) for tr in (getattr(tmp, 'traits', []) or [])],
        }
        self.name_var.set(self.preset_var.get())
        self.hp_var.set(tmp.max_hp);
        self.ac_var.set(tmp.ac)
        self.spd_var.set(getattr(tmp, 'speed', 30));
        self.regen_var.set(getattr(tmp, 'regen', 0))
        self.attacks = [{'name': a.name, 'attack_bonus': a.attack_bonus,
                         'damage_dice_count': a.damage_dice_count,
                         'damage_dice_type': a.damage_dice_type,
                         'damage_modifier': a.damage_modifier,
                         'damage_type': getattr(a, 'damage_type', ''),
                         'range_ft': getattr(a, 'range_ft', 5)} for a in tmp.attacks]
        self._refresh_atk_box()
        self._refresh_atk_box()
        self.editor.set_data(self.chars_data)   # этап 3: пресет доезжает до редактора

    def _refresh_atk_box(self):
        self.atk_box.delete(0, tk.END)
        for a in self.attacks:
            self.atk_box.insert(tk.END,
                f"{a['name']} (+{a['attack_bonus']}, {a['damage_dice_count']}{a['damage_dice_type']}"
                f"{a['damage_modifier']:+d})")

    def _attack_form(self, title, init=None):
        init = dict(init or {'name': 'Атака', 'attack_bonus': 0, 'damage_dice_count': 1,
                             'damage_dice_type': 'd6', 'damage_modifier': 0,
                             'damage_type': '', 'range_ft': 5})
        d = tk.Toplevel(self.win);
        d.title(title);
        d.transient(self.win);
        d.grab_set()
        fit_window_to_screen(d, 360, 430)
        fr = ttk.Frame(d);
        fr.pack(fill='both', expand=True, padx=12, pady=10)
        vars_ = {}
        for key, lab, wid in (('name', 'Название', 24), ('damage_type', 'Тип урона', 18)):
            ttk.Label(fr, text=lab).pack(anchor='w');
            vars_[key] = tk.StringVar(value=init[key])
            ttk.Entry(fr, textvariable=vars_[key], width=wid).pack(anchor='w', pady=(0, 4))
        for key, lab, rng in (('attack_bonus', 'Бонус к попаданию', (-10, 20)),
                              ('damage_dice_count', 'Кол-во костей', (1, 20)),
                              ('damage_modifier', 'Модификатор урона', (-20, 50)),
                              ('range_ft', 'Дальность (фт)', (5, 300))):
            ttk.Label(fr, text=lab).pack(anchor='w');
            vars_[key] = tk.IntVar(value=init[key])
            ttk.Spinbox(fr, from_=rng[0], to=rng[1], textvariable=vars_[key], width=10).pack(anchor='w', pady=(0, 4))
        ttk.Label(fr, text='Тип кости').pack(anchor='w')
        vars_['damage_dice_type'] = tk.StringVar(value=init['damage_dice_type'])
        ttk.Combobox(fr, textvariable=vars_['damage_dice_type'],
                     values=['d4', 'd6', 'd8', 'd10', 'd12', 'd20'], width=8, state='readonly').pack(anchor='w')
        result = {}

        def ok():
            result.update({k: v.get() for k, v in vars_.items()});
            d.destroy()

        def cancel():
            d.destroy()

        ttk.Button(fr, text='Сохранить', command=ok).pack(side='left', padx=6, pady=8)
        ttk.Button(fr, text='Отмена', command=cancel).pack(side='left', pady=8)
        d.wait_window()
        return result or None

    def _add_attack(self):
        a = self._attack_form('Новая атака')
        if a: self.attacks.append(a); self._refresh_atk_box()

    def _edit_attack(self):
        sel = self.atk_box.curselection()
        if not sel: messagebox.showwarning('Внимание', 'Выберите атаку!', parent=self.win); return
        a = self._attack_form('Изменить атаку', self.attacks[sel[0]])
        if a: self.attacks[sel[0]] = a; self._refresh_atk_box()

    def _del_attack(self):
        sel = self.atk_box.curselection()
        if sel: del self.attacks[sel[0]]; self._refresh_atk_box()

    def _confirm_custom(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning('Внимание', 'Дайте существу имя!', parent=self.win);
            return
        if not self.attacks:
            messagebox.showwarning('Внимание', 'Добавьте хотя бы одну атаку!', parent=self.win);
            return
        self.chars_data = self.editor.get_data()
        EnemyFactory.register_type(name,
                                   hp=self.hp_var.get(), ac=self.ac_var.get(),
                                   attacks=self.attacks, speed=self.spd_var.get(),
                                   regen=self.regen_var.get(),
                                   multiattack=self.multiattack_data,
                                   **self.chars_data)
        if name not in self.sim.enemy_types:
            self.sim.enemy_types.append(name)
        self.on_result({'army_type': name, 'strategy': self.strat_var.get()})
        self.win.destroy()
