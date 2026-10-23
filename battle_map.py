import tkinter as tk
from tkinter import ttk, messagebox
import random
from theme_manager import current_palette

CELL_PX = 28  # размер клетки в пикселях
SIDE_COLORS = ['#e74c3c', '#3498db', '#2ecc71', '#f1c40f', '#9b59b6', '#e67e22']


class BattleMap:
    """Модель поля боя: сетка клеток и позиции токенов"""

    def __init__(self, width=24, height=16):
        self.width = width
        self.height = height
        self.positions = {}   # id(enemy) -> (x, y)
        self._enemies = {}    # id(enemy) -> enemy
        self.cell_map = {}  # (x, y) -> enemy

    def cell_free(self, x, y, ignore_id=None):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        occ = self.cell_map.get((x, y))
        return occ is None or id(occ) == ignore_id

    def place(self, enemy, x, y):
        old = self.positions.get(id(enemy))
        if old:
            self.cell_map.pop(old, None)
        self.positions[id(enemy)] = (x, y)
        self.cell_map[(x, y)] = enemy
        self._enemies[id(enemy)] = enemy
        enemy.pos = (x, y)

    def get_pos(self, enemy):
        """Возвращает позицию токена (x, y) или None, если он не на карте"""
        return self.positions.get(id(enemy))

    def enemy_at(self, x, y):
        return self.cell_map.get((x, y))

    def distance_ft(self, a, b):
        """Дистанция в футах: в 5e диагональ = 5 фт, поэтому берём максимум разниц"""
        pa, pb = self.get_pos(a), self.get_pos(b)
        if not pa or not pb:
            return 0
        return max(abs(pa[0] - pb[0]), abs(pa[1] - pb[1])) * 5

    def _zone_for(self, side_idx, total):
        """Каждая сторона получает свою вертикальную полосу поля"""
        w = max(3, self.width // max(1, total))
        x0 = side_idx * w
        x1 = min(self.width, (side_idx + 1) * w) if side_idx < total - 1 else self.width
        return x0, x1

    def _find_any_free(self):
        """Первая свободная клетка где угодно на карте, или None, если карта забита"""
        for yy in range(self.height):
            for xx in range(self.width):
                if self.cell_free(xx, yy):
                    return xx, yy
        return None

    def random_placement(self, sides):
        """Случайная расстановка, но каждая сторона в своей зоне"""
        self.positions.clear()
        self.cell_map.clear()
        self._enemies.clear()
        for i, side in enumerate(sides):
            x0, x1 = self._zone_for(i, len(sides))
            cells = [(x, y) for x in range(x0, x1) for y in range(self.height)]
            random.shuffle(cells)
            for enemy in side:
                enemy.moved_ft = 0
                if not enemy.alive:
                    continue
                while cells:
                    x, y = cells.pop()
                    if self.cell_free(x, y):
                        self.place(enemy, x, y)
                        break
                else:
                    spot = self._find_any_free()  # зона переполнена - селим куда угодно
                    if spot:
                        self.place(enemy, spot[0], spot[1])

    def formation_placement(self, sides):
        """Расстановка шеренгами в своей зоне; переполнение зоны больше НЕ вешает программу"""
        self.positions.clear()
        self.cell_map.clear()
        self._enemies.clear()
        for i, side in enumerate(sides):
            x0, x1 = self._zone_for(i, len(sides))
            for enemy in side:
                enemy.moved_ft = 0
                if not enemy.alive:
                    continue
                spot = None
                # Первая свободная клетка в своей зоне, ряд за рядом (шеренги!)
                for yy in range(self.height):
                    for xx in range(x0, x1):
                        if self.cell_free(xx, yy):
                            spot = (xx, yy)
                            break
                    if spot:
                        break
                if spot is None:  # зона забита под завязку
                    spot = self._find_any_free()
                if spot is None:  # вся карта забита - пропускаем бойца
                    continue
                self.place(enemy, spot[0], spot[1])

    def find_path(self, enemy, target, max_steps, reach_steps=1):
        """BFS-поиск кратчайшего пути (до max_steps шагов) до ближайшей клетки,
        с которой цель досягаема (чебышевское расстояние <= reach_steps).
        Если такой клетки нет - возвращает путь, приближающий к цели максимально.
        Возвращает список клеток БЕЗ стартовой, или None, если идти некуда."""
        start = self.get_pos(enemy)
        tpos = self.get_pos(target)
        if not start or not tpos:
            return None
        eid = id(enemy)
        # 8 направлений, перемешанные - чтобы воины не ходили одной колонной
        dirs = [(-1, -1), (0, -1), (1, -1), (-1, 0),
                (1, 0), (-1, 1), (0, 1), (1, 1)]
        random.shuffle(dirs)

        parents = {start: None}
        frontier = [start]
        best_cell = start
        best_dist = max(abs(start[0] - tpos[0]), abs(start[1] - tpos[1]))

        def rebuild(cell):
            path = []
            cur = cell
            while cur is not None:
                path.append(cur)
                cur = parents[cur]
            return path[::-1][1:]  # без стартовой клетки

        for _ in range(max_steps):
            next_frontier = []
            for (cx, cy) in frontier:
                for dx, dy in dirs:
                    nx, ny = cx + dx, cy + dy
                    if (nx, ny) in parents:
                        continue
                    if not self.cell_free(nx, ny, ignore_id=eid):
                        continue
                    parents[(nx, ny)] = (cx, cy)
                    d = max(abs(nx - tpos[0]), abs(ny - tpos[1]))
                    if d <= reach_steps:
                        return rebuild((nx, ny))  # нашли клетку атаки!
                    if d < best_dist:
                        best_dist = d
                        best_cell = (nx, ny)
                    next_frontier.append((nx, ny))
            frontier = next_frontier
            if not frontier:
                break
        # Цель недоступна - ползем максимально близко по лучшему пути
        if best_cell == start:
            return None
        return rebuild(best_cell)

    def move_towards(self, enemy, target, max_ft, reach_ft=5):
        """Умное движение: BFS-маршрут в обход союзников до клетки атаки.
        Если путь намертво заблокирован толпой - делает случайный 'дрейф'-шаг,
        чтобы пробка понемногу рассасывалась, а не стояла насмерть."""
        steps = max_ft // 5
        reach_steps = max(1, reach_ft // 5)
        path = self.find_path(enemy, target, steps, reach_steps)
        if path:
            self.place(enemy, path[-1][0], path[-1][1])
            return
        # Путь не найден - ерзаем в случайную свободную соседнюю клетку (анти-пробка)
        pos = self.get_pos(enemy)
        if not pos:
            return
        x, y = pos
        free = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                if self.cell_free(x + dx, y + dy, ignore_id=id(enemy)):
                    free.append((x + dx, y + dy))
        if free:
            nx, ny = random.choice(free)
            self.place(enemy, nx, ny)


class BattleMapUI:
    """Вкладка с картой боя: токены, клетки, перемещения по скорости"""

    def __init__(self):
        self.battle_map = None
        self.selected_enemy = None
        self.auto_move = True  # авто-продвижение к цели в бою

    def setup_map_ui(self):
        for w in self.map_frame.winfo_children():
            w.destroy()
        self.selected_enemy = None

        if not getattr(self, 'sides', None) or not any(self.sides):
            ttk.Label(self.map_frame,
                      text="Сначала создайте армии на вкладке «Настройка армий»",
                      font=('Arial', 12)).pack(pady=50)
            return

        if self.battle_map is None:
            self.battle_map = BattleMap()

        top = ttk.Frame(self.map_frame)
        top.pack(fill='x', pady=5)
        ttk.Button(top, text="🎲 Расставить случайно", command=self.place_random).pack(side='left', padx=5)
        ttk.Button(top, text="🛡 Расставить строем", command=self.place_formation).pack(side='left', padx=5)
        self.auto_move_var = tk.BooleanVar(value=self.auto_move)
        ttk.Checkbutton(top, text="Автоперемещение в бою", variable=self.auto_move_var,
                        command=self._sync_auto_move).pack(side='left', padx=10)
        ttk.Label(top, text="Клетка = 5 фт. Клик по токену — выбрать, клик по зелёной клетке — шаг.",
                  font=('Arial', 9)).pack(side='left', padx=10)

        map_wrap = ttk.Frame(self.map_frame)
        map_wrap.pack(fill='both', expand=True, pady=5)
        map_wrap.grid_rowconfigure(0, weight=1)
        map_wrap.grid_columnconfigure(0, weight=1)
        p = current_palette(self)
        self.map_canvas = tk.Canvas(map_wrap, bg=p['canvas_map'], highlightthickness=1,
                                    highlightbackground=p['border'])
        vbar = ttk.Scrollbar(map_wrap, orient='vertical', command=self.map_canvas.yview)
        hbar = ttk.Scrollbar(map_wrap, orient='horizontal', command=self.map_canvas.xview)
        self.map_canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.map_canvas.grid(row=0, column=0, sticky='nsew')
        vbar.grid(row=0, column=1, sticky='ns')
        hbar.grid(row=1, column=0, sticky='ew')
        self.map_canvas.configure(scrollregion=(0, 0,
                                                self.battle_map.width * CELL_PX,
                                                self.battle_map.height * CELL_PX))
        self.map_canvas.bind('<Button-1>', self.on_map_click)
        self.draw_map()

    def _sync_auto_move(self):
        self.auto_move = self.auto_move_var.get()

    def place_random(self):
        self.battle_map.random_placement(self.sides)
        self.draw_map()

    def place_formation(self):
        self.battle_map.formation_placement(self.sides)
        self.draw_map()

    def draw_map(self):
        if not hasattr(self, 'map_canvas'):
            return
        p = current_palette(self)
        c = self.map_canvas
        c.delete('all')
        bm = self.battle_map
        for x in range(bm.width + 1):
            c.create_line(x * CELL_PX, 0, x * CELL_PX, bm.height * CELL_PX, fill=p['canvas_grid'])
        for y in range(bm.height + 1):
            c.create_line(0, y * CELL_PX, bm.width * CELL_PX, y * CELL_PX, fill=p['canvas_grid'])

        # Подсветка клеток, достижимых с остатком скорости выбранного токена
        if self.selected_enemy and self.selected_enemy.alive:
            pos = bm.get_pos(self.selected_enemy)
            if pos:
                reach = (self.selected_enemy.speed - getattr(self.selected_enemy, 'moved_ft', 0)) // 5
                for dy in range(-reach, reach + 1):
                    for dx in range(-reach, reach + 1):
                        nx, ny = pos[0] + dx, pos[1] + dy
                        if bm.cell_free(nx, ny, ignore_id=id(self.selected_enemy)):
                            c.create_rectangle(nx * CELL_PX + 1, ny * CELL_PX + 1,
                                               (nx + 1) * CELL_PX - 1, (ny + 1) * CELL_PX - 1,
                                               fill=p['canvas_reach'], outline='')
        # Токены
        for i, side in enumerate(self.sides):
            color = SIDE_COLORS[i % len(SIDE_COLORS)]
            for enemy in side:
                pos = bm.get_pos(enemy)
                if not pos:
                    continue
                x, y = pos
                cx, cy = x * CELL_PX + CELL_PX // 2, y * CELL_PX + CELL_PX // 2
                r = CELL_PX // 2 - 3
                fill = color if enemy.alive else '#555555'
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill,
                              outline='white' if enemy is self.selected_enemy else 'black',
                              width=2 if enemy is self.selected_enemy else 1)
                label = enemy.name.split('_')[-1][:2]
                c.create_text(cx, cy, text=label, fill='white', font=('Arial', 8, 'bold'))

    def on_map_click(self, event):
        """Обрабатывает клик по карте: сначала переводим координаты экрана в координаты карты"""
        bm = self.battle_map
        cx = self.map_canvas.canvasx(event.x)
        cy = self.map_canvas.canvasy(event.y)
        x, y = int(cx) // CELL_PX, int(cy) // CELL_PX

        clicked = bm.enemy_at(x, y)
        if clicked and clicked.alive:
            self.selected_enemy = clicked
            self.draw_map()
            return
        if self.selected_enemy and self.selected_enemy.alive:
            pos = bm.get_pos(self.selected_enemy)
            if not pos:
                return
            dist = max(abs(x - pos[0]), abs(y - pos[1])) * 5
            left = self.selected_enemy.speed - getattr(self.selected_enemy, 'moved_ft', 0)
            if dist == 0:
                return
            if dist > left:
                messagebox.showinfo("Движение",
                                    f"Не хватает скорости: нужно {dist} фт, осталось {left} фт")
                return
            if bm.cell_free(x, y, ignore_id=id(self.selected_enemy)):
                bm.place(self.selected_enemy, x, y)
                self.selected_enemy.moved_ft = getattr(self.selected_enemy, 'moved_ft', 0) + dist
                self.draw_map()