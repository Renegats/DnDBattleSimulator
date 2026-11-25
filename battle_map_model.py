"""Модель поля боя с учётом размера существ. Без tkinter и без Qt.

Занятость хранится в ПОЛУКЛЕТКАХ (2,5 фт): крошечный занимает 1 полуклетку,
средний 2×2, большой 4×4, огромный 6×6, громадный 8×8. Позиция — якорь (левый
верхний угол пятна) в клетках, допускается шаг 0,5 для крошечных.

Дистанция считается между краями пятен, поэтому огромный тролль достаёт дальше
от своего края, а не от центра клетки. Трупы по-прежнему прозрачны для движения.
"""
import random

from creature_size import size_cells, size_label, size_space, half_cells


def _clean(v):
    v = v / 2.0
    return int(v) if float(v).is_integer() else v


class BattleMap:
    """Сетка клеток, пятна существ и маршруты с учётом габаритов."""

    def __init__(self, width=24, height=16):
        self.width = int(width)
        self.height = int(height)
        self.positions = {}      # id(enemy) -> (x, y) в клетках
        self._enemies = {}       # id(enemy) -> enemy
        self.cell_map = {}       # (int x, int y) -> enemy (якорь, для совместимости)
        self._occ = {}           # (hx, hy) полуклетки -> enemy

    # ---------- габариты ----------
    @staticmethod
    def span_of(enemy):
        return half_cells(getattr(enemy, 'size', None))

    @staticmethod
    def cells_of(enemy):
        return size_cells(getattr(enemy, 'size', None))

    def footprint(self, enemy):
        """(x, y, cells) пятна существа или None, если оно не на карте."""
        p = self.get_pos(enemy)
        if p is None:
            return None
        return (p[0], p[1], self.cells_of(enemy))

    def _anchor_h(self, enemy):
        p = self.positions.get(id(enemy))
        if p is None:
            return None
        return (int(round(p[0] * 2)), int(round(p[1] * 2)))

    def _fits(self, hx, hy, n):
        return (0 <= hx and 0 <= hy
                and hx + n <= self.width * 2 and hy + n <= self.height * 2)

    def _area_free(self, hx, hy, n, ignore_id=None):
        if not self._fits(hx, hy, n):
            return False
        for yy in range(hy, hy + n):
            for xx in range(hx, hx + n):
                occ = self._occ.get((xx, yy))
                if occ is None or id(occ) == ignore_id or not occ.alive:
                    continue
                return False
        return True

    @staticmethod
    def _gap_h(pa, na, pb, nb):
        gx = max(0, pa[0] - (pb[0] + nb), pb[0] - (pa[0] + na))
        gy = max(0, pa[1] - (pb[1] + nb), pb[1] - (pa[1] + na))
        return max(gx, gy)

    @staticmethod
    def _distance_from_gap(gap_h):
        """Футы между краями пятен. gap=0 (пятна соседи) → 5 фт.

        Та же формула, что у distance_ft: (gap + 2) * 2.5. Сравнивать сам gap
        с reach в полуклетках нельзя: reach 5 фт — это 2 полуклетки, но в них
        уже сидит эта «+2», и мили останавливались на gap=2 (10 фт).
        """
        return (gap_h + 2) * 2.5

    def _within_reach(self, gap_h, reach_ft):
        return self._distance_from_gap(gap_h) <= float(reach_ft) + 1e-9

    # ---------- занятость ----------
    def cell_free(self, x, y, ignore_id=None, cells=None, enemy=None):
        """Свободно ли место под пятно. enemy задаёт габариты, cells — явно."""
        if enemy is not None:
            n = self.span_of(enemy)
        elif cells is not None:
            n = max(1, int(round(cells * 2)))
        else:
            n = 2
        return self._area_free(int(round(x * 2)), int(round(y * 2)), n, ignore_id)

    def unplace(self, enemy):
        eid = id(enemy)
        for key, occ in list(self._occ.items()):
            if occ is enemy:
                self._occ.pop(key, None)
        for key, occ in list(self.cell_map.items()):
            if occ is enemy:
                self.cell_map.pop(key, None)
        self.positions.pop(eid, None)
        self._enemies.pop(eid, None)

    def place(self, enemy, x, y):
        self.unplace(enemy)
        hx, hy = int(round(x * 2)), int(round(y * 2))
        n = self.span_of(enemy)
        for yy in range(hy, hy + n):
            for xx in range(hx, hx + n):
                self._occ[(xx, yy)] = enemy
        pos = (_clean(hx), _clean(hy))
        self.positions[id(enemy)] = pos
        self._enemies[id(enemy)] = enemy
        self.cell_map[(hx // 2, hy // 2)] = enemy
        enemy.pos = pos

    def get_pos(self, enemy):
        return self.positions.get(id(enemy))

    def enemy_at(self, x, y):
        return self._occ.get((int(x * 2), int(y * 2)))

    def distance_ft(self, a, b):
        """Расстояние между краями пятен в футах (соседи = 5 фт)."""
        pa, pb = self._anchor_h(a), self._anchor_h(b)
        if pa is None or pb is None:
            return 0.0
        return self._distance_from_gap(
            self._gap_h(pa, self.span_of(a), pb, self.span_of(b)))

    # ---------- расстановка ----------
    def _zone_for(self, side_idx, total):
        w = max(3, self.width // max(1, total))
        x0 = side_idx * w
        x1 = min(self.width, (side_idx + 1) * w) if side_idx < total - 1 else self.width
        return x0, x1

    def _find_any_free(self, n, step):
        for hy in range(0, self.height * 2 - n + 1, step):
            for hx in range(0, self.width * 2 - n + 1, step):
                if self._area_free(hx, hy, n):
                    return hx, hy
        return None

    def _reset(self):
        self.positions.clear()
        self.cell_map.clear()
        self._enemies.clear()
        self._occ.clear()

    def random_placement(self, sides):
        """Случайно по своей зоне; крупные расселяются первыми."""
        self._reset()
        for i, side in enumerate(sides):
            x0, x1 = self._zone_for(i, len(sides))
            for e in side:
                e.moved_ft = 0
            living = sorted((e for e in side if e.alive), key=lambda e: -self.span_of(e))
            for e in living:
                n = self.span_of(e)
                step = 1 if n == 1 else 2
                cells = [(hx, hy)
                         for hx in range(x0 * 2, x1 * 2 - n + 1, step)
                         for hy in range(0, self.height * 2 - n + 1, step)]
                random.shuffle(cells)
                for hx, hy in cells:
                    if self._area_free(hx, hy, n):
                        self.place(e, hx / 2, hy / 2)
                        break
                else:
                    spot = self._find_any_free(n, step)
                    if spot:
                        self.place(e, spot[0] / 2, spot[1] / 2)

    def formation_placement(self, sides):
        """Шеренгами в своей зоне; крупные первыми, чтобы им хватило места."""
        self._reset()
        for i, side in enumerate(sides):
            x0, x1 = self._zone_for(i, len(sides))
            for e in side:
                e.moved_ft = 0
            living = sorted((e for e in side if e.alive), key=lambda e: -self.span_of(e))
            for e in living:
                n = self.span_of(e)
                step = 1 if n == 1 else 2
                spot = None
                for hy in range(0, self.height * 2 - n + 1, step):
                    for hx in range(x0 * 2, x1 * 2 - n + 1, step):
                        if self._area_free(hx, hy, n):
                            spot = (hx, hy)
                            break
                    if spot:
                        break
                if spot is None:
                    spot = self._find_any_free(n, step)
                if spot is None:
                    continue
                self.place(e, spot[0] / 2, spot[1] / 2)

    # ---------- маршруты ----------
    @staticmethod
    def _rebuild(parents, cell):
        path = []
        cur = cell
        while cur is not None:
            path.append((_clean(cur[0]), _clean(cur[1])))
            cur = parents[cur]
        return path[::-1][1:]

    def find_path(self, enemy, target, max_steps, reach_steps=1, reach_ft=None,
                  allow=None):
        """BFS с учётом габаритов: пятно должно помещаться в каждую клетку пути.
        Возвращает список якорей в клетках (без стартового) или None.
        reach_ft — досягаемость в футах (приоритетнее reach_steps)."""
        start, goal = self._anchor_h(enemy), self._anchor_h(target)
        if start is None or goal is None:
            return None
        n, tn = self.span_of(enemy), self.span_of(target)
        step = 1 if n == 1 else 2
        if reach_ft is None:
            reach_ft = max(0, int(reach_steps)) * 5
        levels = max(1, int(max_steps * 2) // step)
        if self._within_reach(self._gap_h(start, n, goal, tn), reach_ft):
            return []
        dirs = [(-1, -1), (0, -1), (1, -1), (-1, 0),
                (1, 0), (-1, 1), (0, 1), (1, 1)]
        random.shuffle(dirs)
        parents = {start: None}
        frontier = [start]
        best, best_gap = start, self._gap_h(start, n, goal, tn)
        for _ in range(levels):
            nxt = []
            for cx, cy in frontier:
                for dx, dy in dirs:
                    nx, ny = cx + dx * step, cy + dy * step
                    if (nx, ny) in parents:
                        continue
                    if not self._area_free(nx, ny, n, ignore_id=id(enemy)):
                        continue
                    if allow is not None and not allow(nx, ny):
                        continue
                    parents[(nx, ny)] = (cx, cy)
                    gap = self._gap_h((nx, ny), n, goal, tn)
                    if self._within_reach(gap, reach_ft):
                        return self._rebuild(parents, (nx, ny))
                    if gap < best_gap:
                        best_gap, best = gap, (nx, ny)
                    nxt.append((nx, ny))
            frontier = nxt
            if not frontier:
                break
        if best == start:
            return None
        return self._rebuild(parents, best)

    def move_towards(self, enemy, target, max_ft, reach_ft=5, allow=None):
        already = int(getattr(enemy, 'moved_ft', 0) or 0)
        steps = max(0, (int(max_ft) - already) // 5)
        before = self.get_pos(enemy)
        path = self.find_path(enemy, target, steps, reach_ft=reach_ft, allow=allow)
        if path is not None:
            if path:
                nx, ny = path[-1]
                self.place(enemy, nx, ny)
                if before:
                    moved = max(abs(nx - before[0]), abs(ny - before[1])) * 5
                    enemy.moved_ft = min(max_ft, getattr(enemy, 'moved_ft', 0) + moved)
            return
        anchor = self._anchor_h(enemy)
        if anchor is None:
            return
        n = self.span_of(enemy)
        step = 1 if n == 1 else 2
        free = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                hx, hy = anchor[0] + dx * step, anchor[1] + dy * step
                if self._area_free(hx, hy, n, ignore_id=id(enemy)):
                    if allow is not None and not allow(hx, hy):
                        continue
                    free.append((hx, hy))
        if free:
            hx, hy = random.choice(free)
            self.place(enemy, hx / 2, hy / 2)
            enemy.moved_ft = min(max_ft, getattr(enemy, 'moved_ft', 0) + step * 2.5)

    # ---------- сводка для интерфейса ----------
    def describe(self, enemy):
        size = getattr(enemy, 'size', None)
        return f'{size_label(size)} · {size_space(size)}'