import tkinter as tk
from tkinter import ttk, messagebox
import random
from theme_manager import current_palette
from battle_map_model import BattleMap

CELL_PX = 28  # размер клетки в пикселях
SIDE_COLORS = ['#e74c3c', '#3498db', '#2ecc71', '#f1c40f', '#9b59b6', '#e67e22']

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
            raise RuntimeError(
                "battle_map не установлен владельцем до setup_map_ui - нарушен контракт owner-managed injection (см. BattleSimulator.create_armies)")

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
            for enemy in sorted(side, key=lambda e: e.alive):
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