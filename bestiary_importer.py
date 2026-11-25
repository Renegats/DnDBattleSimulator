import time
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import threading

import bestiary_core
from ui_components import ScrollableFrame, fit_window_to_screen


def fetch_search_page(query, headers, timeout=10, attempts=3):
    """Поиск на dnd.su. query передаётся в params — requests сам кодирует URL.

    Повтор на обрыв связи и 429/5xx. Успешный ответ с первого раза сеть не дёргает повторно.
    """
    last = None
    tries = max(1, int(attempts))
    for attempt in range(tries):
        try:
            response = requests.get('https://dnd.su/bestiary/', params={'search': query},
                                    headers=headers, timeout=timeout)
            response.encoding = 'utf-8'
            if response.status_code in bestiary_core.RETRY_STATUS and attempt + 1 < tries:
                time.sleep(bestiary_core.RETRY_BACKOFF[min(attempt, len(bestiary_core.RETRY_BACKOFF) - 1)])
                continue
            return response
        except (requests.Timeout, requests.ConnectionError) as exc:
            last = exc
            if attempt + 1 >= tries:
                raise
            time.sleep(bestiary_core.RETRY_BACKOFF[min(attempt, len(bestiary_core.RETRY_BACKOFF) - 1)])
    if last:
        raise last
    raise RuntimeError('Сайт не ответил')


class BestiaryImporter:
    """Окно импорта Tk. Разбор страницы делегирован bestiary_core."""

    HEADERS = bestiary_core.HEADERS

    def __init__(self, parent_root, simulator, on_imported=None, on_cancel=None):
        self.parent_root = parent_root
        self.simulator = simulator
        self.search_results = []
        self.selected_monster = None
        self.on_imported = on_imported
        self.on_cancel = on_cancel

        # ================= АСИНХРОННЫЙ СЕТЕВОЙ СЛОЙ =================
    def _async(self, work, on_success):
        """work() выполняется в ФОНОВОМ потоке (не блокирует UI!),
        а on_success(результат) вызывается обратно в UI-потоке через after."""
        def runner():
            try:
                result = work()
            except Exception as e:
                self.parent_root.after(0, lambda exc=e: self._safe(self._on_error, exc))
                return
            self.parent_root.after(0, lambda r=result: self._safe(on_success, r))
        threading.Thread(target=runner, daemon=True).start()

    def _safe(self, func, arg):
        """Вызываем колбэк ТОЛЬКО если окно импорта ещё живо (иначе игнорим)."""
        try:
            if self.import_window.winfo_exists():
                func(arg)
        except tk.TclError:
            pass  # окно закрыли в момент возврата из сети - тихо выходим

    def _on_error(self, exc):
        messagebox.showerror("Ошибка сети", f"Не удалось получить данные:\n{exc}",
                             parent=self.import_window)

    def _set_busy(self, busy):
        """Блокируем ввод на время запроса + показываем, что идёт загрузка."""
        state = 'disabled' if busy else 'normal'
        self.search_entry.config(state=state)

    # ================= ОКНО =================
    def open_import_window(self):
        self.import_window = tk.Toplevel(self.parent_root)
        self.import_window.title("📖 Импорт монстров из бестиария")
        fit_window_to_screen(self.import_window, 900, 700)
        self.import_window.transient(self.parent_root)
        self.import_window.protocol('WM_DELETE_WINDOW', self._on_close)

        main_frame = ttk.Frame(self.import_window)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        search_frame = ttk.LabelFrame(main_frame, text="Поиск монстра")
        search_frame.pack(fill='x', pady=5)
        ttk.Label(search_frame, text="Название:").pack(side='left', padx=5)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        self.search_entry.pack(side='left', padx=5)
        self.search_entry.bind('<Return>', lambda e: self.search_monster())
        ttk.Button(search_frame, text="🔍 Искать", command=self.search_monster).pack(side='left', padx=5)

        results_frame = ttk.LabelFrame(main_frame, text="Результаты поиска")
        results_frame.pack(fill='both', expand=True, pady=5)
        self.results_listbox = tk.Listbox(results_frame, height=10)
        self.results_listbox.pack(fill='both', expand=True, padx=5, pady=5)
        self.results_listbox.bind('<<ListboxSelect>>', self.on_monster_select)

        preview_frame = ttk.LabelFrame(main_frame, text="Предпросмотр монстра")
        preview_frame.pack(fill='both', expand=True, pady=5)
        self.preview_scroll = ScrollableFrame(preview_frame)
        self.preview_scroll.pack(fill='both', expand=True)

        self.import_btn = ttk.Button(main_frame, text="✨ Импортировать в симулятор",
                                     command=self.import_selected_monster, state='disabled')
        self.import_btn.pack(pady=10)

    def _on_close(self):
        try:
            self.import_window.destroy()
        except tk.TclError:
            pass
        if self.on_cancel:
            self.on_cancel()

    # ПОИСК
    def search_monster(self):
        query = self.search_var.get().strip()
        if not query:
            messagebox.showwarning("Внимание", "Введите название монстра!", parent=self.import_window)
            return
        self._set_busy(True)
        self.selected_monster = None
        self.import_btn.config(state='disabled')
        self.results_listbox.delete(0, tk.END)
        self.results_listbox.insert(tk.END, "⏳ Ищем на dnd.su... (окно живёт, идёт загрузка)")

        def work():
            response = fetch_search_page(query, self.HEADERS, timeout=10)
            response.encoding = 'utf-8'
            if response.status_code != 200:
                raise RuntimeError(f"Сайт ответил кодом {response.status_code}")
            return response.text

        def ok(html):
            self._set_busy(False)
            self.parse_search_results(html, query)

        self._async(work, ok)

    def parse_search_results(self, html, query):
        self.results_listbox.delete(0, tk.END)
        self.search_results = bestiary_core.search_monsters(html, query)
        for entry in self.search_results:
            self.results_listbox.insert(tk.END, entry['name'])
        if not self.search_results:
            messagebox.showinfo("Результаты",
                                "Монстры с таким именем не найдены. Попробуй другое название!",
                                parent=self.import_window)

    # ================= ВЫБОР / ЗАГРУЗКА СТАТБЛОКА (тоже не виснет!) =================
    def on_monster_select(self, event):
        selection = self.results_listbox.curselection()
        if not selection:
            return
        monster_data = self.search_results[selection[0]]
        self.import_btn.config(state='disabled')
        # пометка в превью, что грузимся
        for w in self.preview_scroll.scrollable_frame.winfo_children():
            w.destroy()
        ttk.Label(self.preview_scroll.scrollable_frame,
                  text="⏳ Загружаем статблок монстра...", font=('Arial', 11)).pack(pady=20)

        def work():
            return bestiary_core.fetch_cached(monster_data['url'])

        def ok(html):
            monster_stats = self.parse_statblock(html, monster_data['url'])
            self.display_monster_preview(monster_stats)
            self.selected_monster = monster_stats
            self.import_btn.config(state='normal')

        self._async(work, ok)

    def parse_statblock(self, html, url='https://dnd.su'):
        return bestiary_core.parse_statblock(html, url)

    def display_monster_preview(self, monster):
        for widget in self.preview_scroll.scrollable_frame.winfo_children():
            widget.destroy()
        preview = self.preview_scroll.scrollable_frame
        for note in list(monster.get('errors') or []) + list(monster.get('warnings') or []):
            ttk.Label(preview, text=f"⚠ {note}", font=('Arial', 10, 'bold'),
                      wraplength=560, justify='left').pack(anchor='w', padx=10, pady=1)
        if monster.get('warnings') or monster.get('errors'):
            ttk.Label(preview, text='Импорт не заблокирован: карточку можно забрать и поправить.',
                      font=('Arial', 9, 'italic')).pack(anchor='w', padx=10, pady=(0, 6))
        ttk.Label(preview, text=f"👾 {monster['name']}", font=('Arial', 14, 'bold')).pack(pady=5)

        head = []
        if monster.get('size'): head.append(monster['size'])
        if monster.get('type'): head.append(monster['type'])
        if monster.get('cr'):   head.append(f"CR {monster['cr']}")
        if monster.get('prof_bonus'): head.append(f"Бонус мастерства {monster['prof_bonus']}")
        if head:
            ttk.Label(preview, text=' · '.join(head), font=('Arial', 10, 'italic')).pack(anchor='w', padx=10)

        ttk.Label(preview, text=f"❤️ Хиты: {monster['hp']}   🛡️ КД: {monster['ac']}   "
                                f"👟 Скорость: {monster.get('speed', 30)} фт",
                  font=('Arial', 11)).pack(anchor='w', padx=10)
        if monster.get('regen'):
            ttk.Label(preview, text=f"💚 Регенерация: {monster['regen']}", font=('Arial', 11)).pack(anchor='w', padx=10)

        from statblock_parser import ABILITY_ORDER, ABILITY_LABEL
        sc, md = monster.get('ability_scores') or {}, monster.get('ability_mods') or {}
        if sc:
            cells = []
            for k in ABILITY_ORDER:
                if k in sc:
                    sign = '+' if md.get(k, 0) >= 0 else ''
                    cells.append(f"{ABILITY_LABEL[k]} {sc[k]} ({sign}{md.get(k, 0)})")
            ttk.Label(preview, text=' · '.join(cells), font=('Arial', 10, 'bold')).pack(anchor='w', padx=10,
                                                                                        pady=(4, 0))
        for label, key in [('Спасброски', 'saves'), ('Навыки', 'skills'), ('Чувства', 'senses')]:
            d = monster.get(key) or {}
            if d:
                txt = ', '.join(f"{kk} {vv}".strip() for kk, vv in d.items())
                ttk.Label(preview, text=f"{label}: {txt}", font=('Arial', 10)).pack(anchor='w', padx=10)
        for label, key in [('Уязвимости', 'vulnerabilities'), ('Сопротивления', 'resistances'),
                           ('Иммунитеты', 'immunities'), ('Иммун. к условиям', 'condition_immunities'),
                           ('Языки', 'languages')]:
            lst = monster.get(key) or []
            if lst:
                ttk.Label(preview, text=f"{label}: {', '.join(lst)}", font=('Arial', 10)).pack(anchor='w', padx=10)

        traits = monster.get('traits') or []
        if traits:
            ttk.Label(preview, text="✨ Особенности:", font=('Arial', 12, 'bold')).pack(anchor='w', pady=(8, 2))
            for tr in traits:
                ttk.Label(preview, text=f"• {tr['name']}. {tr['desc']}",
                          font=('Arial', 9), wraplength=560, justify='left').pack(anchor='w', padx=20)

        legendary = monster.get('legendary_actions') or None
        if legendary:
            ttk.Label(preview, text=f"👑 Легендарные действия ({legendary.get('per_round')}/раунд):",
                      font=('Arial', 12, 'bold')).pack(anchor='w', pady=(8, 2))
            for option in legendary.get('options') or []:
                mark = ' · в бою' if option.get('usable') else ''
                ttk.Label(preview, text=f"• {option.get('name')} (стоит {option.get('cost', 1)}){mark}",
                          font=('Arial', 10)).pack(anchor='w', padx=20)
        ttk.Label(preview, text="⚔️ Атаки:", font=('Arial', 12, 'bold')).pack(anchor='w', pady=(10, 5))
        for attack in monster['attacks']:
            attack_text = (f"• {attack['name']} ({attack['attack_bonus']:+d}, "
                           f"{bestiary_core.format_damage(attack)})")
            ttk.Label(preview, text=attack_text, font=('Arial', 10)).pack(anchor='w', padx=20)

        if not sc and not traits and not (monster.get('saves') or monster.get('skills')):
            ttk.Label(preview, text="⚠ В источнике не указаны характеристики/особенности "
                                    "(описание дополняется на dnd.su)",
                      font=('Arial', 9, 'italic'), foreground='#888888').pack(anchor='w', padx=10, pady=(8, 0))

    # ИМПОРТ
    def import_selected_monster(self):
        if not self.selected_monster:
            return
        monster_type = self.selected_monster['name']
        attacks_data = [{
            'name': a['name'], 'attack_bonus': a['attack_bonus'],
            'damage_dice_count': a['damage_dice_count'],
            'damage_dice_type': a['damage_dice_type'],
            'damage_modifier': a['damage_modifier'],
            'damage_type': a.get('damage_type', ''),
            'range_ft': a.get('range_ft', 5),
        } for a in self.selected_monster['attacks']]

        from factory import EnemyFactory
        chars = {k: v for k, v in self.selected_monster.items()
                 if k in ('ability_scores', 'ability_mods', 'saves', 'skills', 'senses',
                          'vulnerabilities', 'resistances', 'immunities',
                          'condition_immunities', 'languages', 'cr', 'prof_bonus',
                          'size', 'type', 'traits', 'legendary_actions',
                          'legendary_resistance', 'lair_actions', 'special_actions',
                          'bonus_actions', 'reactions')}
        EnemyFactory.register_type(monster_type,
                                   hp=self.selected_monster['hp'],
                                   ac=self.selected_monster['ac'],
                                   attacks=attacks_data,
                                   speed=self.selected_monster.get('speed', 30),
                                   regen=self.selected_monster.get('regen', 0),
                                   multiattack=self.selected_monster.get('multiattack'),
                                   **chars)
        if monster_type not in self.simulator.enemy_types:
            self.simulator.enemy_types.append(monster_type)
            messagebox.showinfo("Успех",
                                f"✨ Монстр {monster_type} импортирован!",
                                parent=self.import_window)
        else:
            messagebox.showinfo("Информация",
                                f"Монстр {monster_type} уже в списке!",
                                parent=self.import_window)

        self.import_window.destroy()
        if self.on_imported:
            self.on_imported(monster_type)