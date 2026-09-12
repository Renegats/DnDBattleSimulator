import tkinter as tk
from tkinter import ttk, messagebox
import random

CELL_PX = 28  # размер клетки в пикселях
SIDE_COLORS = ['#e74c3c', '#3498db', '#2ecc71', '#f1c40f', '#9b59b6', '#e67e22']


class BattleMap:
    """Модель поля боя: сетка клеток и позиции токенов"""

    def __init__(self, width=24, height=16):
        self.width = width
        self.height = height
        self.positions = {}   # id(enemy) -> (x, y)
        self._enemies = {}    # id(enemy) -> enemy

    def cell_free(self, x, y, ignore_id=None):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        for eid, (px, py) in self.positions.items():
            if (px, py) == (x, y) and eid != ignore_id:
                return False
        return True

    def place(self, enemy, x, y):
        self.positions[id(enemy)] = (x, y)
        self._enemies[id(enemy)] = enemy
        enemy.pos = (x, y)

    def get_pos(self, enemy):
        return self.positions.get(id(enemy))

    def enemy_at(self, x, y):
        for eid, (px, py) in self.positions.items():
            if (px, py) == (x, y):
                return self._enemies.get(eid)
        return None

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

    def random_placement(self, sides):
        """Случайная расстановка, но каждая сторона в своей зоне"""
        self.positions.clear()
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

    def formation_placement(self, sides):
        """Расстановка шеренгами у края своей зоны"""
        self.positions.clear()
        self._enemies.clear()
        for i, side in enumerate(sides):
            x0, x1 = self._zone_for(i, len(sides))
            cols = max(1, x1 - x0)
            k = 0
            for enemy in side:
                enemy.moved_ft = 0
                if not enemy.alive:
                    continue
                x = x0 + (k % cols)
                y = (k // cols) % self.height
                while not self.cell_free(x, y):
                    y = (y + 1) % self.height
                self.place(enemy, x, y)
                k += 1

    def move_towards(self, enemy, target, max_ft):
        """Жадное движение к цели (для авто-продвижения в бою), обходя занятые клетки"""
        pos, tpos = self.get_pos(enemy), self.get_pos(target)
        if not pos or not tpos:
            return
        x, y = pos
        for _ in range(max_ft // 5):
            if (x, y) == tpos:
                break
            dx = (tpos[0] > x) - (tpos[0] < x)
            dy = (tpos[1] > y) - (tpos[1] < y)
            moved = False
            for nx, ny in ((x + dx, y + dy), (x + dx, y), (x, y + dy)):
                if self.cell_free(nx, ny, ignore_id=id(enemy)):
                    x, y = nx, ny
                    moved = True
                    break
            if not moved:
                break
        self.place(enemy, x, y)


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

        self.map_canvas = tk.Canvas(self.map_frame,
                                    width=self.battle_map.width * CELL_PX,
                                    height=self.battle_map.height * CELL_PX,
                                    bg='#2e4d2e', highlightthickness=1)
        self.map_canvas.pack(pady=5)
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
        c = self.map_canvas
        c.delete('all')
        bm = self.battle_map
        for x in range(bm.width + 1):
            c.create_line(x * CELL_PX, 0, x * CELL_PX, bm.height * CELL_PX, fill='#4d7a4d')
        for y in range(bm.height + 1):
            c.create_line(0, y * CELL_PX, bm.width * CELL_PX, y * CELL_PX, fill='#4d7a4d')

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
                                               fill='#3d6b3d', outline='')
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
        bm = self.battle_map
        x, y = event.x // CELL_PX, event.y // CELL_PX
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