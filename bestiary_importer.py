import tkinter as tk
from tkinter import ttk, messagebox
import requests
from bs4 import BeautifulSoup
import re
from entities import Enemy, Attack
from ui_components import ScrollableFrame, fit_window_to_screen


class BestiaryImporter:
    """Класс для импорта монстров с dnd.su"""

    # --- Шаблоны для парсинга (атрибуты КЛАССА - доступны через self.откуда угодно) ---
    MONSTER_URL_RE = re.compile(r'/(?:multiverse/)?bestiary/\d+[-_][\w\-]+/?$')
    ATTACK_RE = re.compile(
        r'(?P<name>[А-ЯЁA-Z][^.\n]{2,80}?)\.\s*'
        r'(?:Рукопашная|Дальнобойная)\s+атака\s+оружием:?\s*'
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

    def __init__(self, parent_root, simulator):
        self.parent_root = parent_root
        self.simulator = simulator  # Ссылка на главный симулятор
        self.search_results = []
        self.selected_monster = None

    def open_import_window(self):
        """Открывает окно импорта монстров"""
        self.import_window = tk.Toplevel(self.parent_root)
        self.import_window.title("📖 Импорт монстров из бестиария")
        fit_window_to_screen(self.import_window, 900, 700)
        self.import_window.transient(self.parent_root)  # Окно будет поверх главного

        # Основной фрейм
        main_frame = ttk.Frame(self.import_window)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Поисковая секция
        search_frame = ttk.LabelFrame(main_frame, text="Поиск монстра")
        search_frame.pack(fill='x', pady=5)

        ttk.Label(search_frame, text="Название:").pack(side='left', padx=5)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        self.search_entry.pack(side='left', padx=5)
        self.search_entry.bind('<Return>', lambda e: self.search_monster())  # Поиск по Enter

        ttk.Button(search_frame, text="🔍 Искать",
                   command=self.search_monster).pack(side='left', padx=5)

        # Секция результатов поиска
        results_frame = ttk.LabelFrame(main_frame, text="Результаты поиска")
        results_frame.pack(fill='both', expand=True, pady=5)

        # Listbox для результатов
        self.results_listbox = tk.Listbox(results_frame, height=10)
        self.results_listbox.pack(fill='both', expand=True, padx=5, pady=5)
        self.results_listbox.bind('<<ListboxSelect>>', self.on_monster_select)

        # Секция предпросмотра статблока
        preview_frame = ttk.LabelFrame(main_frame, text="Предпросмотр монстра")
        preview_frame.pack(fill='both', expand=True, pady=5)

        # Прокручиваемый фрейм для предпросмотра
        self.preview_scroll = ScrollableFrame(preview_frame)
        self.preview_scroll.pack(fill='both', expand=True)

        # Кнопка импорта
        self.import_btn = ttk.Button(main_frame, text="✨ Импортировать в симулятор",
                                     command=self.import_selected_monster,
                                     state='disabled')
        self.import_btn.pack(pady=10)

    def search_monster(self):
        """Ищет монстра на сайте dnd.su"""
        query = self.search_var.get().strip()
        if not query:
            messagebox.showwarning("Внимание", "Введите название монстра!")
            return

        try:
            # Запрос к бестиарию
            search_url = f"https://dnd.su/bestiary/?search={query}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(search_url, headers=headers, timeout=10)
            response.encoding = 'utf-8'

            if response.status_code == 200:
                self.parse_search_results(response.text, query)
            else:
                messagebox.showerror("Ошибка", f"Не удалось подключиться к сайту: {response.status_code}")

        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка поиска: {str(e)}")

    def parse_search_results(self, html, query):
        """Парсит результаты поиска: оставляем ТОЛЬКО монстров, у которых запрос есть в ИМЕНИ"""
        soup = BeautifulSoup(html, 'html.parser')
        self.results_listbox.delete(0, tk.END)
        self.search_results = []
        seen = set()

        query_lower = query.lower()
        for link in soup.find_all('a', href=True):
            href = link['href']
            # Сито 1: только ссылки вида /bestiary/255-black-pudding/
            if not self.MONSTER_URL_RE.search(href):
                continue
            name = link.get_text(strip=True)
            # Сито 2: запрос должен быть В НАЗВАНИИ (русском или английском в скобках)
            # Это сразу выкидывает аболетов, заргонов и прочих "слизевых" по описанию
            if query_lower not in name.lower():
                continue
            if not name or href in seen:
                continue
            seen.add(href)
            url = href if href.startswith('http') else f'https://dnd.su{href}'
            self.search_results.append({'name': name, 'url': url})

        # Красота: названия, начинающиеся с запроса, встают наверх списка
        self.search_results.sort(key=lambda e: (not e['name'].lower().startswith(query_lower),
                                                e['name'].lower()))
        for entry in self.search_results:
            self.results_listbox.insert(tk.END, entry['name'])

        if not self.search_results:
            messagebox.showinfo("Результаты",
                                "Монстры с таким именем не найдены. Попробуй другое название!")

    def on_monster_select(self, event):
        """Обрабатывает выбор монстра из списка"""
        selection = self.results_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        monster_data = self.search_results[index]
        self.load_monster_stats(monster_data['url'])

    def load_monster_stats(self, url):
        """Загружает и парсит статистику монстра"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = 'utf-8'

            if response.status_code == 200:
                monster_stats = self.parse_statblock(response.text)
                self.display_monster_preview(monster_stats)
                self.selected_monster = monster_stats
                self.import_btn.config(state='normal')

        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка загрузки: {str(e)}")

    def parse_statblock(self, html):
        """Парсит статблок монстра со страницы dnd.su"""
        soup = BeautifulSoup(html, 'html.parser')
        monster = {'name': '', 'hp': 10, 'ac': 10, 'attacks': [], 'regen': 0}

        # Имя: из <h1> или из <title> ("Мерроу / Бестиарий D&D 5 / Monster Manual")
        name = ''
        h1 = soup.find('h1')
        if h1:
            name = h1.get_text(strip=True)
        if not name and soup.title and soup.title.string:
            name = soup.title.string.split('/')[0].strip()
        # Убираем английское имя в скобках
        monster['name'] = re.sub(r'\s*\[.*?\]', '', name).strip() or 'Без имени'

        text = soup.get_text()

        hp = re.search(r'(?:Хиты|Hit\s+Points)[^\d]{0,20}(\d+)', text, re.I)
        if hp:
            monster['hp'] = int(hp.group(1))
        ac = re.search(r'(?:Класс\s+Доспеха|Armor\s+Class)[^\d]{0,20}(\d+)', text, re.I)
        if ac:
            monster['ac'] = int(ac.group(1))
        regen = re.search(r'(?:восстанавливает|регенерация)[^\d]{0,40}(\d+)\s+хитов', text, re.I)
        if regen:
            monster['regen'] = int(regen.group(1))

        monster['attacks'] = self.parse_attacks(text)
        return monster

    def parse_attacks(self, text):
        """Парсит атаки вида: Ложноножка. Рукопашная атака оружием: +5 к попаданию...
        Попадание: 6 (1к6 + 3) дробящего урона плюс 18 (4к8) урона кислотой."""
        attacks = []
        seen = set()
        for m in self.ATTACK_RE.finditer(text):
            name = m.group('name').strip(' _*')
            bonus = int(m.group('bonus'))
            # Ищем кости урона в окне сразу после "+N к попаданию"
            window = text[m.end(): m.end() + 250]
            dm = self.DICE_RE.search(window)
            if not dm:
                continue
            count, die = int(dm.group(1)), int(dm.group(2))
            mod = int(dm.group(3).replace(' ', '')) if dm.group(3) else 0
            # Тип урона ищем вокруг костей
            type_window = window[:dm.end() + 60].lower()
            dtype = next((full for stem, full in self.DAMAGE_TYPE_MAP if stem in type_window), '')

            key = (name, bonus, count, die)
            if key in seen:
                continue
            seen.add(key)
            attacks.append({
                'name': name,
                'attack_bonus': bonus,
                'damage_dice_count': count,
                'damage_dice_type': f'd{die}',  # внутри симулятора кости всё равно через "d"
                'damage_modifier': mod,
                'damage_type': dtype
            })

        if not attacks:
            attacks.append({'name': 'Атака', 'attack_bonus': 0, 'damage_dice_count': 1,
                            'damage_dice_type': 'd6', 'damage_modifier': 0, 'damage_type': ''})
        return attacks

    def display_monster_preview(self, monster):
        """Отображает предпросмотр монстра"""
        for widget in self.preview_scroll.scrollable_frame.winfo_children():
            widget.destroy()

        preview = self.preview_scroll.scrollable_frame

        ttk.Label(preview, text=f"👾 {monster['name']}", font=('Arial', 14, 'bold')).pack(pady=5)
        ttk.Label(preview, text=f"❤️ Хиты: {monster['hp']}", font=('Arial', 11)).pack(anchor='w', padx=10)
        ttk.Label(preview, text=f"🛡️ КД: {monster['ac']}", font=('Arial', 11)).pack(anchor='w', padx=10)

        ttk.Label(preview, text="⚔️ Атаки:", font=('Arial', 12, 'bold')).pack(anchor='w', pady=(10, 5))
        for attack in monster['attacks']:
            attack_text = f"• {attack['name']} ({attack['attack_bonus']:+d}, {attack['damage_dice_count']}{attack['damage_dice_type']}{attack['damage_modifier']:+d})"
            ttk.Label(preview, text=attack_text, font=('Arial', 10)).pack(anchor='w', padx=20)

    def import_selected_monster(self):
        """Импортирует выбранного монстра в симулятор"""
        if not self.selected_monster:
            return

        attacks = []
        for atk_data in self.selected_monster['attacks']:
            attack = Attack(
                name=atk_data['name'],
                attack_bonus=atk_data['attack_bonus'],
                damage_dice_count=atk_data['damage_dice_count'],
                damage_dice_type=atk_data['damage_dice_type'],
                damage_modifier=atk_data['damage_modifier'],
                damage_type=atk_data.get('damage_type', '')
            )
            attacks.append(attack)

        # Создаем шаблон врага (нам не нужен инстанс для фабрики, нам нужно имя типа)
        monster_type = self.selected_monster['name']

        # Добавляем тип в список симулятора!
        if monster_type not in self.simulator.enemy_types:
            self.simulator.enemy_types.append(monster_type)

            # МАГИЯ! 🪄 Обновляем все Combobox-ы в главном окне, чтобы новый монстр там появился!
            for child in self.simulator.types_frame.winfo_children():
                for widget in child.winfo_children():
                    if isinstance(widget, ttk.Combobox):
                        current_values = list(widget['values'])
                        if monster_type not in current_values:
                            current_values.append(monster_type)
                            widget.config(values=current_values)

            # Также можно сохранить шаблон в Factory, но пока просто добавили в список

            messagebox.showinfo("Успех",
                                f"✨ Монстр {monster_type} успешно импортирован и добавлен в выпадающие списки армий!")
        else:
            messagebox.showinfo("Информация", f"Монстр {monster_type} уже есть в списке!")

        self.import_window.destroy()