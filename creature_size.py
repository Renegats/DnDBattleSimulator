"""Размер существа по RAW 5e (Space) и геометрия занимаемого места.

Крошечный 2,5×2,5 фт (0,5 клетки), Маленький/Средний 5×5 (1), Большой 10×10 (2),
Огромный 15×15 (3), Громадный 20×20 (4). Модель поля хранит занятость в
полуклетках, поэтому крошечные реально помещаются по четыре в клетку.
"""
from functools import lru_cache

SIZE_ORDER = ['tiny', 'small', 'medium', 'large', 'huge', 'gargantuan']

SIZE_CELLS = {'tiny': 0.5, 'small': 1.0, 'medium': 1.0,
              'large': 2.0, 'huge': 3.0, 'gargantuan': 4.0}

SIZE_LABEL = {'tiny': 'Крошечный', 'small': 'Маленький', 'medium': 'Средний',
              'large': 'Большой', 'huge': 'Огромный', 'gargantuan': 'Громадный'}

SIZE_SPACE = {'tiny': '2,5×2,5 фт', 'small': '5×5 фт', 'medium': '5×5 фт',
              'large': '10×10 фт', 'huge': '15×15 фт', 'gargantuan': '20×20 фт'}

SIZE_LABELS = [SIZE_LABEL[k] for k in SIZE_ORDER]

_TRIGGERS = [
    ('gargantuan', ('громадн', 'гигантск', 'исполин', 'gargantuan')),
    ('huge', ('огромн', 'huge')),
    ('large', ('больш', 'крупн', 'large')),
    ('small', ('маленьк', 'малый', 'мала', 'малое', 'small')),
    ('tiny', ('крошеч', 'крохот', 'миниатюр', 'tiny')),
    ('medium', ('средн', 'medium')),
]


def canon_size(text) -> str:
    """Русский/английский текст статблока -> ключ размера. Пусто -> Средний."""
    if not text:
        return 'medium'
    if text in SIZE_CELLS:
        return text
    return _canon_size_text(str(text).strip().lower())


@lru_cache(maxsize=256)
def _canon_size_text(low):
    if low in SIZE_CELLS:
        return low
    for key, stems in _TRIGGERS:
        if any(stem in low for stem in stems):
            return key
    return 'medium'


def size_cells(text) -> float:
    return SIZE_CELLS[canon_size(text)]


def size_label(text) -> str:
    return SIZE_LABEL[canon_size(text)]


def size_space(text) -> str:
    return SIZE_SPACE[canon_size(text)]


def half_cells(text) -> int:
    """Сторона пятна в полуклетках: 1 / 2 / 4 / 6 / 8."""
    return max(1, int(round(size_cells(text) * 2)))


def space_distance_ft(a, b) -> float:
    """Дистанция между КРАЯМИ пятен (чебышев), как в 5e при игре по сетке.

    Используется, когда карты нет: тот же расчёт, что и в BattleMap.distance_ft,
    чтобы мозг и исполнитель не расходились в оценке досягаемости.
    """
    pa, pb = getattr(a, 'pos', None), getattr(b, 'pos', None)
    if not pa or not pb:
        return 0.0
    na, nb = half_cells(getattr(a, 'size', None)), half_cells(getattr(b, 'size', None))
    ax, ay = pa[0] * 2, pa[1] * 2
    bx, by = pb[0] * 2, pb[1] * 2
    gx = max(0, ax - (bx + nb), bx - (ax + na))
    gy = max(0, ay - (by + nb), by - (ay + na))
    return (max(gx, gy) + 2) * 2.5