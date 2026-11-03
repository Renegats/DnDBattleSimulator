import tkinter as tk
from tkinter import ttk, messagebox
import requests
from bs4 import BeautifulSoup
import re
import threading
from entities import Enemy, Attack
from ui_components import ScrollableFrame, fit_window_to_screen
from statblock_parser import parse_characteristics, extract_statblock_text, extract_battle_text


class BestiaryImporter:
    """Класс для импорта монстров с dnd.su"""

    # --- Шаблоны для парсинга (атрибуты КЛАССА) ---
    MONSTER_URL_RE = re.compile(r'/(?:multiverse/)?bestiary/\d+[-_][\w\-]+/?$')
    ATTACK_RE = re.compile(
        r'(?P<name>[А-ЯЁA-Z][^.\n]{2,80}?)\.\s*'
        r'(?P<kind>Рукопашная|Дальнобойная)\s+атака\s+оружием:?\s*'
        r'(?P<bonus>[+-]?\d+)\s+к\s+попаданию',
        re.IGNORECASE)
    DICE_RE = re.compile(r'(\d+)\s*[кkd]\s*(\d+)(?:\s*([+-]\s*\d+))?')
    DAMAGE_TYPE_MAP = [
        ('рубящ', 'рубящий'), ('колющ', 'колющий'), ('пронзающ', 'пронзающий'),
        ('дробящ', 'дробящий'), ('огнен', 'огненный'), ('кислот', 'кислотный'),
        ('холод', 'холод'), ('электрич', 'электрический'), ('молни', 'молнии'),
        ('яд', 'яд'), ('психич', 'психический'), ('силов', 'силовое поле'),
        ('излуч', 'излучение'), ('некротич', 'некротический'), ('гром', 'гром'),
    ]
    HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                             'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'}

    NUM_WORDS = {'одна':1,'одну':1,'одной':1,'одним':1,'одним':1,
                 'две':2,'двух':2,'двум':2,'двумя':2,'две':2,
                 'три':3,'трёх':3,'трём':3,'четыре':4,'четырёх':4,'четырём':4,
                 'пять':5,'пяти':5,'шесть':6,'шести':6,'семь':7,'семи':7,
                 'восемь':8,'восьми':8,'девять':9,'девяти':9,'десять':10,'десяти':10}
    STRIKE_RE = re.compile(
        r'(?:(?P<num>одн[ауюе]|дв[ауюеи]|тр[еиё]|четыр[еиё]?|пяти?|шести?|семи?|восьми?|девяти?|десяти?|\d+)\s+)?'
        r'атак[ауеийок]*\s+(?:оружием\s+|частью\s+|по\s+)?'
        r'(?P<part>[А-ЯЁа-яёA-Za-z][\w\-]*)', re.IGNORECASE)
    SUFFIXES = sorted(['иями','иям','ами','ями','ам','ям','ом','ем','ов','ев',
                       'ах','ях','у','ю','а','я','и','ы','е','о'], key=len, reverse=True)

    @classmethod
    def _norm_word(cls, w):
        w = w.lower().strip()
        for suf in cls.SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                return w[:-len(suf)]
        return w

    def _match_attack(self, part, attacks):
        np = self._norm_word(part)
        if not np:
            return None
        for a in attacks:
            words = {self._norm_word(x) for x in a['name'].split()}
            if np in words or any(np == wd or (len(np) >= 3 and (np in wd or wd in np)) for wd in words):
                return a['name']
        return None

    def parse_multiattack(self, text, attacks):
        """Вытаскивает мультиатаку из окна текста; возвращает list-of-dict или None."""
        m = re.search(r'(?:Мультиатака|Multiattack)', text, re.IGNORECASE)
        if not m:
            return None
        window = text[m.end(): m.end() + 320]          # окно на всю фразу мультиатаки
        strikes, seen_pairs = [], set()
        for sm in self.STRIKE_RE.finditer(window):
            raw = sm.group('num')
            if raw is None:
                cnt = 1
            elif raw.isdigit():
                cnt = int(raw)
            else:
                cnt = self.NUM_WORDS.get(self._norm_word(raw) + '' if False else raw.lower(), None)
                if cnt is None:
                    # пробуем по основе слова
                    cnt = next((v for k, v in self.NUM_WORDS.items() if k.startswith(raw.lower()[:3])), 1)
            name = self._match_attack(sm.group('part'), attacks)
            if not name:
                continue                                # преамбула/мусор - отбрасываем
            key = (name, cnt)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            strikes.append({'attack': name, 'count': cnt})
        return strikes or None                          # None => воин бьёт одной атакой (деградация)

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
            response = requests.get(f"https://dnd.su/bestiary/?search={query}",
                                    headers=self.HEADERS, timeout=10)
            response.encoding = 'utf-8'
            if response.status_code != 200:
                raise RuntimeError(f"Сайт ответил кодом {response.status_code}")
            return response.text

        def ok(html):
            self._set_busy(False)
            self.parse_search_results(html, query)

        self._async(work, ok)

    def parse_search_results(self, html, query):
        soup = BeautifulSoup(html, 'html.parser')
        self.results_listbox.delete(0, tk.END)
        self.search_results = []
        seen = set()
        query_lower = query.lower()
        for link in soup.find_all('a', href=True):
            href = link['href']
            if not self.MONSTER_URL_RE.search(href):
                continue
            name = link.get_text(strip=True)
            if query_lower not in name.lower():
                continue
            if not name or href in seen:
                continue
            seen.add(href)
            url = href if href.startswith('http') else f'https://dnd.su{href}'
            self.search_results.append({'name': name, 'url': url})
        self.search_results.sort(key=lambda e: (not e['name'].lower().startswith(query_lower),
                                                e['name'].lower()))
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
            response = requests.get(monster_data['url'], headers=self.HEADERS, timeout=10)
            response.encoding = 'utf-8'
            if response.status_code != 200:
                raise RuntimeError(f"Сайт ответил кодом {response.status_code}")
            return response.text

        def ok(html):
            monster_stats = self.parse_statblock(html)
            self.display_monster_preview(monster_stats)
            self.selected_monster = monster_stats
            self.import_btn.config(state='normal')

        self._async(work, ok)

    # ================= ПАРСИНГ (чистый, без сети) =================
    def parse_statblock(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        monster = {'name': '', 'hp': 10, 'ac': 10, 'attacks': [], 'regen': 0, 'speed': 30}
        name = ''
        h1 = soup.find('h1')
        if h1:
            name = h1.get_text(strip=True)
        if not name and soup.title and soup.title.string:
            name = soup.title.string.split('/')[0].strip()
        name = re.sub(r'\s*\[.*?\]', '', name)
        name = re.split(r'[—–-]\s*Бестиарий', name)[0]
        name = re.sub(r'\s*\([A-Za-z]{2,6}\)\s*[—–-].*$', '', name)
        monster['name'] = name.strip() or 'Без имени'

        # ДВА окна активной редакции: ref (справочный+особенности+хиты/КД/скорость)
        # и battle (Действия -> атаки/мультиатака). Парсим по окнам, НЕ по полному
        # get_text(), иначе ловим обе редакции (5e24/5e14) -> дубль атак/хвостов.
        ref = extract_statblock_text(soup)
        battle = extract_battle_text(soup)

        spd = re.search(r'Скорость\s*(\d+)\s*футов', ref, re.I)
        if spd:
            monster['speed'] = int(spd.group(1))
        hp = re.search(r'(?:Хиты|Hit\s+Points)[^\d]{0,20}(\d+)', ref, re.I)
        if hp:
            monster['hp'] = int(hp.group(1))
        ac = re.search(r'(?:Класс\s+Доспеха|Armor\s+Class)[^\d]{0,20}(\d+)', ref, re.I)
        if ac:
            monster['ac'] = int(ac.group(1))
        regen = re.search(r'(?:восстанавливает|регенерация)[^\d]{0,40}(\d+)\s+хитов', ref, re.I)
        if regen:
            monster['regen'] = int(regen.group(1))

        monster['attacks'] = self.parse_attacks(battle)
        monster['multiattack'] = self.parse_multiattack(battle, monster['attacks'])
        monster.update(parse_characteristics(soup, ref))
        return monster

    def parse_attacks(self, text):
        attacks = []
        seen = set()
        for m in self.ATTACK_RE.finditer(text):
            name = m.group('name').strip(' _*')
            bonus = int(m.group('bonus'))
            window = text[m.end(): m.end() + 250]
            rm = re.search(r'дистанция\s*(\d+)', window)
            reach = re.search(r'досягаемость\s*(\d+)', window)
            if m.group('kind').lower().startswith('дально') and rm:
                range_ft = int(rm.group(1))
            elif reach:
                range_ft = int(reach.group(1))
            else:
                range_ft = 5
            dm = self.DICE_RE.search(window)
            if not dm:
                continue
            count, die = int(dm.group(1)), int(dm.group(2))
            mod = int(dm.group(3).replace(' ', '')) if dm.group(3) else 0
            type_window = window[:dm.end() + 60].lower()
            dtype = next((full for stem, full in self.DAMAGE_TYPE_MAP if stem in type_window), '')
            key = (name, bonus, count, die)
            if key in seen:
                continue
            seen.add(key)
            attacks.append({'name': name, 'attack_bonus': bonus,
                            'damage_dice_count': count, 'damage_dice_type': f'd{die}',
                            'damage_modifier': mod, 'damage_type': dtype, 'range_ft': range_ft})
        if not attacks:
            attacks.append({'name': 'Атака', 'attack_bonus': 0, 'damage_dice_count': 1,
                            'damage_dice_type': 'd6', 'damage_modifier': 0,
                            'damage_type': '', 'range_ft': 5})
        return attacks

    def display_monster_preview(self, monster):
        for widget in self.preview_scroll.scrollable_frame.winfo_children():
            widget.destroy()
        preview = self.preview_scroll.scrollable_frame
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

        ttk.Label(preview, text="⚔️ Атаки:", font=('Arial', 12, 'bold')).pack(anchor='w', pady=(10, 5))
        for attack in monster['attacks']:
            attack_text = (f"• {attack['name']} ({attack['attack_bonus']:+d}, "
                           f"{attack['damage_dice_count']}{attack['damage_dice_type']}"
                           f"{attack['damage_modifier']:+d})")
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
                          'size', 'type', 'traits')}
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