"""Рельеф клетки и укрытие по сетке 5e.

Клетка — 5 футов. Стена непроходима и непрозрачна. Трудная местность и вода
удваивают стоимость входа (каждая нога стоит две). Половинное и укрытие на три
четверти проходимы: бонус к КД и спасброску Ловкости, если в клетке стоит цель
или линия на неё пересекает такую клетку. Полное укрытие тоже проходимо, но
цель в такой клетке выбрать нельзя, а линия сквозь клетку блокируется целиком.

Укрытие между существами — правило сетки: из угла пятна атакующего в углы
каждой клетки цели. Атакующий берёт угол и клетку с наименьшим укрытием.
1–2 перекрытые линии — половинное, 3 — на три четверти, все четыре стеной —
полное. Существо на линии даёт не больше половинного. Линия, которая только
коснулась угла, клетку не перекрывает; линия вдоль ребра — перекрывает.
"""
import math

COVER_NONE = 'none'
COVER_HALF = 'half'
COVER_THREE_QUARTERS = 'three_quarters'
COVER_TOTAL = 'total'

COVER_RANK = {
    COVER_NONE: 0,
    COVER_HALF: 1,
    COVER_THREE_QUARTERS: 2,
    COVER_TOTAL: 3,
}

COVER_BONUS = {
    COVER_NONE: 0,
    COVER_HALF: 2,
    COVER_THREE_QUARTERS: 5,
    COVER_TOTAL: 0,
}

COVER_LABEL = {
    COVER_NONE: 'без укрытия',
    COVER_HALF: 'половинное укрытие (+2)',
    COVER_THREE_QUARTERS: 'укрытие на три четверти (+5)',
    COVER_TOTAL: 'полное укрытие',
}

KIND_WALL = 'wall'
KIND_DIFFICULT = 'difficult'
KIND_WATER = 'water'
KIND_HALF = 'half'
KIND_THREE_QUARTERS = 'three_quarters'
KIND_TOTAL = 'total'

KINDS = (
    KIND_WALL, KIND_DIFFICULT, KIND_WATER,
    KIND_HALF, KIND_THREE_QUARTERS, KIND_TOTAL,
)

KIND_LABEL = {
    KIND_WALL: 'Стена',
    KIND_DIFFICULT: 'Трудная местность',
    KIND_WATER: 'Вода',
    KIND_HALF: 'Половинное укрытие',
    KIND_THREE_QUARTERS: 'Укрытие на три четверти',
    KIND_TOTAL: 'Полное укрытие',
}

BLOCKS_MOVE = frozenset((KIND_WALL,))
OPAQUE = frozenset((KIND_WALL, KIND_TOTAL))
DIFFICULT = frozenset((KIND_DIFFICULT, KIND_WATER))
SIGHT_KINDS = frozenset((KIND_WALL, KIND_TOTAL, KIND_HALF, KIND_THREE_QUARTERS))

_LINE_LEVEL = {
    KIND_WALL: 'wall',
    KIND_TOTAL: 'wall',
    KIND_THREE_QUARTERS: 'three',
    KIND_HALF: 'half',
}

_LEVEL_RANK = {'clear': 0, 'half': 1, 'three': 2, 'wall': 3}

SQUARE_COVER = {
    KIND_HALF: COVER_HALF,
    KIND_THREE_QUARTERS: COVER_THREE_QUARTERS,
    KIND_TOTAL: COVER_TOTAL,
    KIND_WALL: COVER_TOTAL,
}

_KIND_ALIASES = {
    'wall': KIND_WALL, 'стена': KIND_WALL, 'препятствие': KIND_WALL,
    'obstacle': KIND_WALL, 'block': KIND_WALL,
    'difficult': KIND_DIFFICULT, 'трудная': KIND_DIFFICULT,
    'труднопроходимая': KIND_DIFFICULT, 'difficult_terrain': KIND_DIFFICULT,
    'water': KIND_WATER, 'вода': KIND_WATER,
    'half': KIND_HALF, 'half_cover': KIND_HALF, 'половинное': KIND_HALF,
    'three_quarters': KIND_THREE_QUARTERS, 'three-quarters': KIND_THREE_QUARTERS,
    '3/4': KIND_THREE_QUARTERS, 'три четверти': KIND_THREE_QUARTERS,
    'total': KIND_TOTAL, 'total_cover': KIND_TOTAL, 'полное': KIND_TOTAL,
}


def canon_kind(value):
    """Ключ типа клетки или None, если это ластик либо неизвестный текст."""
    if value is None:
        return None
    key = str(value).strip().lower()
    if not key or key in ('erase', 'ластик', 'none', 'clear'):
        return None
    return _KIND_ALIASES.get(key)


def lesser_cover(left, right):
    if COVER_RANK[left] <= COVER_RANK[right]:
        return left
    return right


def greater_cover(left, right):
    if COVER_RANK[left] >= COVER_RANK[right]:
        return left
    return right


def segment_overlaps_cell(x0, y0, x1, y1, left, top, right, bottom):
    """Отрезок пересекает замкнутый прямоугольник отрезком ненулевой длины.

    Касание одним углом — не пересечение. Ход вдоль ребра — пересечение.
    """
    dx = float(x1) - float(x0)
    dy = float(y1) - float(y0)
    t0, t1 = 0.0, 1.0
    checks = (
        (-dx, float(x0) - float(left)),
        (dx, float(right) - float(x0)),
        (-dy, float(y0) - float(top)),
        (dy, float(bottom) - float(y0)),
    )
    for param, quota in checks:
        if abs(param) < 1e-12:
            if quota < -1e-12:
                return False
            continue
        cut = quota / param
        if param < 0:
            if cut > t1:
                return False
            if cut > t0:
                t0 = cut
        else:
            if cut < t0:
                return False
            if cut < t1:
                t1 = cut
    return t1 - t0 > 1e-8


def _cells_along_scan(x0, y0, x1, y1):
    """Перебор окна вокруг отрезка. Эталон для проверки быстрого обхода."""
    min_x, max_x = (x0, x1) if x0 <= x1 else (x1, x0)
    min_y, max_y = (y0, y1) if y0 <= y1 else (y1, y0)
    cx0 = int(math.floor(min_x)) - 1
    cx1 = int(math.floor(max_x)) + 1
    cy0 = int(math.floor(min_y)) - 1
    cy1 = int(math.floor(max_y)) + 1
    found = []
    for cy in range(cy0, cy1 + 1):
        for cx in range(cx0, cx1 + 1):
            if segment_overlaps_cell(x0, y0, x1, y1, cx, cy, cx + 1, cy + 1):
                found.append((cx, cy))
    return found


# Геометрия отрезка не зависит от рельефа. В одном раунде одни и те же
# углы клеток проверяются десятки раз — список клеток запоминаем.
_CELL_CACHE = {}
_CELL_CACHE_LIMIT = 50000


def cells_along(x0, y0, x1, y1):
    """Клетки, через внутренность или ребро которых проходит отрезок.

    Идём по столбцам или по рядам — их число линейно от длины, — и оставляем
    клетку только если её прямоугольник реально пересекается с отрезком.
    Набор совпадает с полным перебором окна.
    """
    x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
    key = (x0, y0, x1, y1)
    cached = _CELL_CACHE.get(key)
    if cached is not None:
        return cached
    found = _cells_along_walk(x0, y0, x1, y1)
    if len(_CELL_CACHE) >= _CELL_CACHE_LIMIT:
        _CELL_CACHE.clear()
    _CELL_CACHE[key] = found
    return found


def _cells_along_walk(x0, y0, x1, y1):
    if abs(x1 - x0) < 1e-15 and abs(y1 - y0) < 1e-15:
        return ((int(math.floor(x0)), int(math.floor(y0))),)
    found = []
    seen = set()

    def add(cx, cy):
        if (cx, cy) in seen:
            return
        seen.add((cx, cy))
        if segment_overlaps_cell(x0, y0, x1, y1, cx, cy, cx + 1, cy + 1):
            found.append((cx, cy))

    min_x, max_x = (x0, x1) if x0 <= x1 else (x1, x0)
    min_y, max_y = (y0, y1) if y0 <= y1 else (y1, y0)
    # Точка ровно на линии сетки принадлежит двум клеткам — захватываем обе.
    c0 = int(math.floor(min_x - 1e-9))
    c1 = int(math.floor(max_x + 1e-9))
    r0 = int(math.floor(min_y - 1e-9))
    r1 = int(math.floor(max_y + 1e-9))
    dx = x1 - x0
    dy = y1 - y0
    if abs(dx) >= abs(dy):
        for cx in range(c0, c1 + 1):
            left = max(min_x, float(cx))
            right = min(max_x, float(cx + 1))
            if right < left - 1e-12:
                continue
            ya = y0 + dy * ((left - x0) / dx)
            yb = y0 + dy * ((right - x0) / dx)
            ylo, yhi = (ya, yb) if ya <= yb else (yb, ya)
            for cy in range(int(math.floor(ylo - 1e-9)), int(math.floor(yhi + 1e-9)) + 1):
                add(cx, cy)
    else:
        for cy in range(r0, r1 + 1):
            bottom = max(min_y, float(cy))
            top = min(max_y, float(cy + 1))
            if top < bottom - 1e-12:
                continue
            xa = x0 + dx * ((bottom - y0) / dy)
            xb = x0 + dx * ((top - y0) / dy)
            xlo, xhi = (xa, xb) if xa <= xb else (xb, xa)
            for cx in range(int(math.floor(xlo - 1e-9)), int(math.floor(xhi + 1e-9)) + 1):
                add(cx, cy)
    return tuple(found)


def line_obstruction(x0, y0, x1, y1, terrain, ignore, creature_cells):
    """clear / half / three / wall — сильнейшее препятствие на отрезке."""
    if abs(float(x1) - float(x0)) < 1e-9 and abs(float(y1) - float(y0)) < 1e-9:
        return 'clear'
    level = 'clear'
    creatures = creature_cells or ()
    skipped = ignore or ()
    for cell in cells_along(x0, y0, x1, y1):
        if cell in skipped:
            continue
        cell_level = _LINE_LEVEL.get((terrain or {}).get(cell), 'clear')
        if cell in creatures and _LEVEL_RANK[cell_level] < _LEVEL_RANK['half']:
            cell_level = 'half'
        if _LEVEL_RANK[cell_level] > _LEVEL_RANK[level]:
            level = cell_level
            if level == 'wall':
                return 'wall'
    return level


def classify_lines(levels):
    """Степень укрытия по числу перекрытых линий из одного угла."""
    if not levels:
        return COVER_NONE
    walls = 0
    hard = 0
    blocked = 0
    for level in levels:
        if level == 'wall':
            walls += 1
            hard += 1
            blocked += 1
        elif level == 'three':
            hard += 1
            blocked += 1
        elif level == 'half':
            blocked += 1
    if walls == len(levels):
        return COVER_TOTAL
    if hard >= 3:
        return COVER_THREE_QUARTERS
    if blocked >= 1:
        return COVER_HALF
    return COVER_NONE


def occupied_squares(anchor, size):
    """Клетки 5 фт пятна. Крошечный занимает одну клетку, в которой стоит."""
    if anchor is None:
        return []
    ax, ay = float(anchor[0]), float(anchor[1])
    span = float(size or 1)
    if span < 1 - 1e-9:
        return [(int(math.floor(ax + 1e-9)), int(math.floor(ay + 1e-9)))]
    count = max(1, int(round(span)))
    x0 = int(math.floor(ax + 1e-9))
    y0 = int(math.floor(ay + 1e-9))
    return [(x0 + ix, y0 + iy) for iy in range(count) for ix in range(count)]


def space_corners(anchor, size):
    """Четыре угла пятна. У среднего это углы клетки, у большого — всего квадрата."""
    ax, ay = float(anchor[0]), float(anchor[1])
    span = float(size or 1)
    if span < 1 - 1e-9:
        span = 0.5
    else:
        span = float(max(1, int(round(span))))
    return (
        (ax, ay),
        (ax + span, ay),
        (ax, ay + span),
        (ax + span, ay + span),
    )


def square_corners(cell):
    cx, cy = cell
    return ((cx, cy), (cx + 1, cy), (cx, cy + 1), (cx + 1, cy + 1))


def cover_against(attacker_anchor, attacker_size, target_anchor, target_size,
                  terrain, creature_cells=()):
    """Наименьшее укрытие цели. Нет позиций — укрытия нет, цель не «за стеной»."""
    if attacker_anchor is None or target_anchor is None:
        return COVER_NONE
    terrain = terrain or {}
    creatures = set(creature_cells or ())
    target_squares = occupied_squares(target_anchor, target_size)
    if not target_squares:
        return COVER_NONE
    ignore = set(target_squares)
    ignore.update(occupied_squares(attacker_anchor, attacker_size))
    corners = space_corners(attacker_anchor, attacker_size)
    best = COVER_TOTAL
    for square in target_squares:
        own = SQUARE_COVER.get(terrain.get(square), COVER_NONE)
        from_corner = COVER_TOTAL
        destinations = square_corners(square)
        for corner in corners:
            levels = [
                line_obstruction(
                    corner[0], corner[1], dest[0], dest[1],
                    terrain, ignore, creatures)
                for dest in destinations
            ]
            from_corner = lesser_cover(from_corner, classify_lines(levels))
            if from_corner == COVER_NONE and own == COVER_NONE:
                break
        best = lesser_cover(best, greater_cover(from_corner, own))
        if best == COVER_NONE:
            return COVER_NONE
    return best


def cover_from_point(origin, target_anchor, target_size, terrain,
                     creature_cells=(), ignore=()):
    """Укрытие цели от точки (центр области). Одна точка, без выбора угла."""
    if origin is None or target_anchor is None:
        return COVER_NONE
    terrain = terrain or {}
    squares = occupied_squares(target_anchor, target_size)
    if not squares:
        return COVER_NONE
    skipped = set(squares)
    skipped.update(ignore or ())
    creatures = set(creature_cells or ())
    ox, oy = float(origin[0]), float(origin[1])
    best = COVER_TOTAL
    for square in squares:
        own = SQUARE_COVER.get(terrain.get(square), COVER_NONE)
        levels = [
            line_obstruction(ox, oy, dest[0], dest[1], terrain, skipped, creatures)
            for dest in square_corners(square)
        ]
        best = lesser_cover(best, greater_cover(classify_lines(levels), own))
        if best == COVER_NONE:
            return COVER_NONE
    return best


def point_blocked(attacker_anchor, attacker_size, point, terrain):
    """Все линии от углов атакующего до точки упираются в непрозрачную клетку."""
    if attacker_anchor is None or point is None:
        return False
    terrain = terrain or {}
    if not any(kind in OPAQUE for kind in terrain.values()):
        return False
    ignore = set(occupied_squares(attacker_anchor, attacker_size))
    px, py = float(point[0]), float(point[1])
    for corner in space_corners(attacker_anchor, attacker_size):
        if line_obstruction(
                corner[0], corner[1], px, py, terrain, ignore, ()) != 'wall':
            return False
    return True
