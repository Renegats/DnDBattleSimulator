"""Модель поля боя с учётом размера существ. Без привязки к интерфейсу.

Занятость хранится в ПОЛУКЛЕТКАХ (2,5 фт): крошечный занимает 1 полуклетку,
средний 2×2, большой 4×4, огромный 6×6, громадный 8×8. Позиция — якорь (левый
верхний угол пятна) в клетках, допускается шаг 0,5 для крошечных.

Дистанция считается между краями пятен, поэтому огромный тролль достаёт дальше
от своего края, а не от центра клетки. Трупы по-прежнему прозрачны для движения.
"""
import math
import random

from creature_size import size_cells, size_label, size_space, half_cells
from rng_channel import active as _active_rng


def _rng():
    """Кости расстановки и обхода. В пакете это генератор боя, иначе random."""
    return _active_rng(random)


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
                _rng().shuffle(cells)
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
        _rng().shuffle(dirs)
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
            hx, hy = _rng().choice(free)
            self.place(enemy, hx / 2, hy / 2)
            enemy.moved_ft = min(max_ft, getattr(enemy, 'moved_ft', 0) + step * 2.5)

    # ---------- сводка для интерфейса ----------
    def describe(self, enemy):
        size = getattr(enemy, 'size', None)
        return f'{size_label(size)} · {size_space(size)}'


# ---------- шаблоны областей 5e ----------
#
# Клетка — 5 футов. Точка начала конуса и линии на сторону света — середина ребра
# пятна, чтобы ось шла по центрам клеток: линия шириной 5 фт занимает один ряд,
# а конус не оставляет дыру в первой клетке. По диагонали точка начала — угол
# пятна (пересечение линий сетки). Клетка входит в область, если шаблон накрывает
# хотя бы половину её площади. Куб и квадрат на плоской карте — блок N×N клеток,
# точка начала в середине ближней грани. Сфера, радиус и цилиндр в плоскости карты
# — круг; высота цилиндра на плоской карте никого не отсекает.

COMPASS = (
    ('восток', 1.0, 0.0),
    ('юго-восток', 1.0, 1.0),
    ('юг', 0.0, 1.0),
    ('юго-запад', -1.0, 1.0),
    ('запад', -1.0, 0.0),
    ('северо-запад', -1.0, -1.0),
    ('север', 0.0, -1.0),
    ('северо-восток', 1.0, -1.0),
)

_SHAPE_ALIASES = {
    'cone': 'cone', 'конус': 'cone',
    'line': 'line', 'линия': 'line',
    'sphere': 'sphere', 'сфера': 'sphere',
    'radius': 'radius', 'радиус': 'radius',
    'cube': 'cube', 'куб': 'cube',
    'square': 'square', 'квадрат': 'square',
    'cylinder': 'cylinder', 'цилиндр': 'cylinder',
}


def canon_shape(shape):
    key = str(shape or '').strip().lower()
    return _SHAPE_ALIASES.get(key, key or 'radius')


def unit_vector(dx, dy):
    length = math.hypot(float(dx), float(dy))
    if length < 1e-9:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def direction_name(dx, dy):
    """Ближнее из восьми направлений. Ось y карты растёт вниз."""
    angle = math.degrees(math.atan2(float(dy), float(dx)))
    index = int(((angle + 22.5) % 360) / 45.0) % 8
    return COMPASS[index][0]


def cardinal_vector(dx, dy):
    """Ближняя сторона света. Нужна кубу: на сетке он не поворачивается."""
    ux, uy = unit_vector(dx, dy)
    if abs(ux) >= abs(uy):
        return (1.0 if ux >= 0 else -1.0, 0.0)
    return (0.0, 1.0 if uy >= 0 else -1.0)


def nearest_intersection(point):
    """Ближний угол клеток к точке в координатах клеток."""
    return (int(math.floor(float(point[0]) + 0.5)),
            int(math.floor(float(point[1]) + 0.5)))


def cube_origin(edge, direction, side_ft):
    """Угол сетки на ближней грани куба так, чтобы блок был по центру края.

    edge — середина ребра или угол, от которого куб уходит в direction.
    """
    count = max(1, int(round(float(side_ft or 5) / 5.0)))
    fx, fy = cardinal_vector(direction[0], direction[1])
    ex, ey = float(edge[0]), float(edge[1])

    def perp(center):
        if count % 2 == 1:
            return int(round(center - 0.5))
        return int(round(center))

    if fx != 0:
        return (int(round(ex)), perp(ey))
    return (perp(ex), int(round(ey)))


def point_distance_ft(battle_map, creature, point):
    """Чебышёв от края пятна до точки, в футах. Точка внутри пятна — 0."""
    pos = battle_map.get_pos(creature) if battle_map is not None else None
    if not pos or point is None:
        return 0.0
    size = float(battle_map.cells_of(creature) or 1)
    ax, ay = float(pos[0]), float(pos[1])
    px, py = float(point[0]), float(point[1])
    if ax <= px <= ax + size:
        dx = 0.0
    else:
        dx = min(abs(px - ax), abs(px - (ax + size)))
    if ay <= py <= ay + size:
        dy = 0.0
    else:
        dy = min(abs(py - ay), abs(py - (ay + size)))
    return max(dx, dy) * 5.0


def footprint_cells(battle_map, creature):
    """Клетки 5 фт, которые занимает существо. Пусто, если его нет на карте."""
    if battle_map is None:
        return frozenset()
    pos = battle_map.get_pos(creature)
    if not pos:
        return frozenset()
    size = float(battle_map.cells_of(creature) or 1)
    ax, ay = float(pos[0]), float(pos[1])
    if size < 1:
        return frozenset([(int(math.floor(ax + 1e-9)), int(math.floor(ay + 1e-9)))])
    count = max(1, int(round(size)))
    x0, y0 = int(math.floor(ax + 1e-9)), int(math.floor(ay + 1e-9))
    return frozenset((x0 + ix, y0 + iy) for ix in range(count) for iy in range(count))


def footprint_center(battle_map, creature):
    pos = battle_map.get_pos(creature) if battle_map is not None else None
    if not pos:
        return None
    size = float(battle_map.cells_of(creature) or 1)
    return (float(pos[0]) + size / 2.0, float(pos[1]) + size / 2.0)


def aim_origin(anchor, size, direction):
    """Точка начала конуса или линии у края пятна в сторону direction."""
    ax, ay = float(anchor[0]), float(anchor[1])
    span = max(0.5, float(size or 1))
    dx, dy = unit_vector(direction[0], direction[1])
    if abs(dx) >= 0.35 and abs(dy) >= 0.35:
        return (ax + span if dx > 0 else ax, ay + span if dy > 0 else ay)
    if abs(dx) > abs(dy):
        return (ax + span if dx > 0 else ax, ay + span / 2.0)
    return (ax + span / 2.0, ay + span if dy > 0 else ay)


def _clip_cell(cell, bounds):
    if bounds is None:
        return True
    width, height = bounds
    cx, cy = cell
    return 0 <= cx < int(width) and 0 <= cy < int(height)


def _sample_covered(cx, cy, predicate, samples=8):
    inside = 0
    total = samples * samples
    step = 1.0 / samples
    for iy in range(samples):
        py = cy + (iy + 0.5) * step
        for ix in range(samples):
            px = cx + (ix + 0.5) * step
            if predicate(px, py):
                inside += 1
    return inside / total >= 0.5 - 1e-9


def _cube_cells(origin, direction, side_ft, bounds):
    count = max(1, int(round(float(side_ft or 5) / 5.0)))
    fx, fy = cardinal_vector(direction[0], direction[1])
    ox, oy = nearest_intersection(origin)
    perp0 = -(count // 2)
    cells = []
    for along in range(count):
        for perp in range(count):
            shift = perp0 + perp
            if fx != 0:
                cx = ox + along if fx > 0 else ox - 1 - along
                cy = oy + shift
            else:
                cy = oy + along if fy > 0 else oy - 1 - along
                cx = ox + shift
            cell = (cx, cy)
            if _clip_cell(cell, bounds):
                cells.append(cell)
    return frozenset(cells)


def _circle_predicate(ox, oy, radius_ft):
    limit = float(radius_ft) + 1e-6

    def predicate(px, py):
        return math.hypot((px - ox) * 5.0, (py - oy) * 5.0) <= limit

    return predicate


def _wedge_predicate(ox, oy, direction, length_ft, half_width_of):
    ux, uy = unit_vector(direction[0], direction[1])
    vx, vy = -uy, ux
    length = float(length_ft) + 1e-6

    def predicate(px, py):
        dx = (px - ox) * 5.0
        dy = (py - oy) * 5.0
        along = dx * ux + dy * uy
        if along <= 1e-6 or along > length:
            return False
        across = abs(dx * vx + dy * vy)
        return across <= half_width_of(along) + 1e-6

    return predicate


def template_cells(shape, origin, direction=None, length_ft=0, width_ft=None, *,
                   bounds=None, height_ft=None):
    """Клетки шаблона. origin — точка в координатах клеток, length_ft — длина,
    радиус или сторона. width_ft задаёт ширину линии (по умолчанию 5).
    height_ft у цилиндра на плоской карте не меняет набор клеток.
    """
    del height_ft
    kind = canon_shape(shape)
    if origin is None:
        return frozenset()
    ox, oy = float(origin[0]), float(origin[1])
    length = max(0.0, float(length_ft or 0))
    if kind in ('cube', 'square'):
        return _cube_cells((ox, oy), direction or (1, 0), length, bounds)
    if kind == 'line':
        width = float(width_ft or 5)
        predicate = _wedge_predicate(
            ox, oy, direction or (1, 0), length, lambda _along: width / 2.0)
        reach = length
    elif kind == 'cone':
        predicate = _wedge_predicate(
            ox, oy, direction or (1, 0), length, lambda along: along / 2.0)
        reach = length
    else:
        predicate = _circle_predicate(ox, oy, length)
        reach = length
    span = int(math.ceil(reach / 5.0)) + 2
    x_min = int(math.floor(ox)) - span
    y_min = int(math.floor(oy)) - span
    cells = []
    for cy in range(y_min, y_min + span * 2 + 3):
        for cx in range(x_min, x_min + span * 2 + 3):
            if not _clip_cell((cx, cy), bounds):
                continue
            if _sample_covered(cx, cy, predicate):
                cells.append((cx, cy))
    return frozenset(cells)


def emanation_cells(battle_map, creature, radius_ft, *, bounds=None):
    """Клетки в пределах radius_ft от края пятна, без клеток самого существа.

    Та же дистанция, что у BattleMap.distance_ft: соседняя клетка — 5 фт.
    """
    if battle_map is None or battle_map.get_pos(creature) is None:
        return frozenset()
    own = footprint_cells(battle_map, creature)
    radius = max(0.0, float(radius_ft or 0))
    pos = battle_map.get_pos(creature)
    size = float(battle_map.cells_of(creature) or 1)
    extra = int(math.ceil(radius / 5.0)) + 2
    x0 = int(math.floor(pos[0])) - extra
    y0 = int(math.floor(pos[1])) - extra
    x1 = int(math.ceil(pos[0] + size)) + extra
    y1 = int(math.ceil(pos[1] + size)) + extra
    anchor = battle_map._anchor_h(creature)
    span = battle_map.span_of(creature)
    cells = []
    for cy in range(y0, y1 + 1):
        for cx in range(x0, x1 + 1):
            cell = (cx, cy)
            if cell in own or not _clip_cell(cell, bounds):
                continue
            gap = BattleMap._gap_h(anchor, span, (cx * 2, cy * 2), 2)
            if BattleMap._distance_from_gap(gap) <= radius + 1e-9:
                cells.append(cell)
    return frozenset(cells)