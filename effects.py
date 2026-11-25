"""Разбор и исполнение действий со спасброском.

Область на карте — шаблон клеток: конус, линия, сфера, радиус, куб, квадрат,
цилиндр. Исполнитель сам выбирает направление или центр так, чтобы задеть больше
врагов и не задеть союзников. Без карты остаётся прежний разбор: все враги
в дистанции, для одной цели — ближайший.
"""
import re

from conditions import (HARD_DISABLE, ability_of, active_conditions, apply_condition,
                       condition_name, creature_uid, describe_applied,
                       describe_removed, effective_speed, has_condition,
                       is_condition_immune, iter_creatures, release_grapples_from,
                       save_text, saving_throw)

_SAVE_RE = re.compile(
    r'спасброс\w*\s+'
    r'(?P<abil>силы|силу|ловкости|телосложения|интеллекта|мудрости|харизмы)'
    r'\s+сл\s*(?P<dc>\d+)',
    re.IGNORECASE)

_DICE = (r'(?P<count>\d+)\s*[кkдd]\s*(?P<die>\d+)'
         r'(?:\s*(?P<sign>[+-])\s*(?P<mod>\d+))?')

_DAMAGE_AFTER = re.compile(
    r'урон(?:а|ом|у)?\s+(?P<dtype>[а-яё][а-яё\s-]{0,40}?)\s+'
    r'(?P<avg>\d+)\s*\(\s*' + _DICE,
    re.IGNORECASE)
_DAMAGE_BEFORE = re.compile(
    r'(?P<dtype>[а-яё]{3,})\s+урон\w*\s+(?P<avg>\d+)\s*\(\s*' + _DICE,
    re.IGNORECASE)

_FT = r'(?:футов\w*|фут|фт|feet|foot|ft)'
_NUM_FT = rf'(\d+)\s*[-–]?\s*{_FT}'

_CONE_RES = (
    re.compile(rf'{_NUM_FT}\s+конус', re.IGNORECASE),
    re.compile(r'конус\w*(?:\s+длиной)?\s+(\d+)', re.IGNORECASE),
    re.compile(r'(\d+)\s*[-–]?\s*-?\s*foot(?:\s*-\s*|\s+)(?:long\s+)?cone', re.IGNORECASE),
    re.compile(r'\bcone\s+(?:of\s+)?(\d+)', re.IGNORECASE),
)
_LINE_RES = (
    re.compile(rf'лин\w*\s+длиной\s+(\d+)\s*{_FT}?', re.IGNORECASE),
    re.compile(rf'{_NUM_FT}\s+лин', re.IGNORECASE),
    re.compile(r'(\d+)\s*[-–]?\s*-?\s*foot(?:\s*-\s*|\s+)(?:long\s+)?line', re.IGNORECASE),
    re.compile(r'\bline\s+(?:that\s+is\s+)?(\d+)\s*(?:feet|foot|ft)\s+long', re.IGNORECASE),
)
_WIDTH_RE = re.compile(
    rf'ширин\w*\s+(\d+)|(\d+)\s*{_FT}\s+ширин|(\d+)\s*(?:feet|foot|ft)\s+wide',
    re.IGNORECASE)
_CUBE_RES = (
    re.compile(rf'{_NUM_FT}\s+куб', re.IGNORECASE),
    re.compile(r'куб\w*\s+со\s+стороной(?:\s+в)?\s+(\d+)', re.IGNORECASE),
    re.compile(r'(\d+)\s*[-–]?\s*-?\s*foot(?:\s*-\s*|\s+)cube', re.IGNORECASE),
    re.compile(r'\bcube\s+(?:of\s+)?(\d+)', re.IGNORECASE),
)
_SQUARE_RES = (
    re.compile(rf'{_NUM_FT}\s+квадрат', re.IGNORECASE),
    re.compile(r'квадрат\w*\s+со\s+стороной(?:\s+в)?\s+(\d+)', re.IGNORECASE),
    re.compile(r'(\d+)\s*[-–]?\s*-?\s*foot(?:\s*-\s*|\s+)square', re.IGNORECASE),
    re.compile(r'\bsquare\s+(?:of\s+)?(\d+)', re.IGNORECASE),
)
_RADIUS_RES = (
    re.compile(r'радиус\w*\s+(\d+)', re.IGNORECASE),
    re.compile(rf'{_NUM_FT}\s+радиус', re.IGNORECASE),
    re.compile(r'(\d+)\s*[-–]?\s*-?\s*foot(?:\s*-\s*|\s+)radius', re.IGNORECASE),
    re.compile(r'\bradius\s+(?:of\s+)?(\d+)', re.IGNORECASE),
    re.compile(r'в\s+радиусе\s+(\d+)', re.IGNORECASE),
    re.compile(r'\bin\s+a\s+(\d+)\s*(?:-| )?(?:foot|feet|ft)\s+radius', re.IGNORECASE),
)
_WITHIN_RE = re.compile(
    rf'в\s+пределах\s+(\d+)\s*{_FT}?|\bwithin\s+(\d+)\s*(?:feet|foot|ft)',
    re.IGNORECASE)
_HEIGHT_RE = re.compile(
    rf'(\d+)\s*{_FT}\s+высот|высот\w*\s+(\d+)|'
    r'(\d+)\s*(?:feet|foot|ft)\s+(?:tall|high)',
    re.IGNORECASE)
_SHAPE_WORD_RE = re.compile(
    r'конус|\bcone\b|лин(?:ия|ии|ию|ей)\b|\bline\b|сфер|\bsphere\b|'
    r'\bкуб\b|\bcube\b|квадрат|\bsquare\b|цилиндр|\bcylinder\b',
    re.IGNORECASE)
_POINT_RE = re.compile(
    r'точк|центр|с\s+центром|point\s+within|centered\s+on', re.IGNORECASE)
_FROM_SELF_RE = re.compile(
    r'от\s+(?:него|неё|себя|вас|дракона)|around\s+(?:it|him|her|you)|'
    r'originating\s+from\s+(?:you|the)',
    re.IGNORECASE)
_CONE_RE = _CONE_RES[0]
_RECHARGE_SPAN = re.compile(
    r'перезарядк\w*\s*(\d+)\s*[–\-—]\s*(\d+)', re.IGNORECASE)
_RECHARGE_ONE = re.compile(r'перезарядк\w*\s*(\d+)', re.IGNORECASE)

# (id, regex). speed_zero — не состояние PHB, только обнуление скорости.
_CONDITION_RES = (
    ('paralyzed', re.compile(r'парализован', re.IGNORECASE)),
    ('poisoned', re.compile(r'отравлен', re.IGNORECASE)),
    ('frightened', re.compile(r'испуган', re.IGNORECASE)),
    ('prone', re.compile(r'сбит\w*(?:\s+\w+){0,3}\s+с\s+ног', re.IGNORECASE)),
    ('grappled', re.compile(r'схвачен', re.IGNORECASE)),
    ('restrained', re.compile(r'опутан', re.IGNORECASE)),
    ('stunned', re.compile(r'ошеломл', re.IGNORECASE)),
    ('blinded', re.compile(r'ослепл', re.IGNORECASE)),
    ('charmed', re.compile(r'очарован', re.IGNORECASE)),
    ('incapacitated', re.compile(r'недееспособ', re.IGNORECASE)),
    ('unconscious', re.compile(r'без сознания|бессознательн', re.IGNORECASE)),
    ('petrified', re.compile(r'окамене', re.IGNORECASE)),
    ('deafened', re.compile(r'оглох', re.IGNORECASE)),
    ('invisible', re.compile(r'невидим', re.IGNORECASE)),
    ('speed_zero', re.compile(
        r'скорост\w+[^.]*?(?:становит\w*|равн\w*)[^.]*?\b0\b', re.IGNORECASE)),
)

_SUPPLEMENT_RE = re.compile(r'присутств|взгляд|ужасающ', re.IGNORECASE)
_DELAYED_RE = re.compile(
    r'начина\w+\s+ход|в этом облаке|пока не наступит', re.IGNORECASE)


def _damage_dict(match):
    if match is None:
        return None
    sign = match.group('sign') or '+'
    modifier = int(match.group('mod') or 0)
    if sign == '-':
        modifier = -modifier
    return {
        'dice_count': int(match.group('count')),
        'dice_type': f"d{match.group('die')}",
        'modifier': modifier,
        'damage_type': (match.group('dtype') or '').strip(),
    }


def parse_damage(text):
    return _damage_dict(_DAMAGE_AFTER.search(text or '')) or _damage_dict(
        _DAMAGE_BEFORE.search(text or ''))


def _half(text):
    return bool(re.search(
        r'половин\w+(?:\s+\w+){0,3}\s+урон|вдвое меньше урона|половину этого урона',
        text or '', re.IGNORECASE))


def parse_duration(text, ability, dc):
    text = text or ''
    repeat = bool(re.search(
        r'повтор\w+\s+этот\s+спасбросок|в конце каждого своего хода',
        text, re.IGNORECASE))
    minutes = re.search(r'на\s+(\d+)\s+минут', text, re.IGNORECASE)
    rounds = re.search(r'на\s+(\d+)\s+раунд', text, re.IGNORECASE)
    cap = None
    if minutes:
        cap = int(minutes.group(1)) * 10
    elif rounds:
        cap = int(rounds.group(1))
    elif re.search(r'на\s+1\s+минуту|на минуту', text, re.IGNORECASE):
        cap = 10
    if re.search(r'до начала следующего хода', text, re.IGNORECASE):
        kind, whose = 'start', 'source'
    elif re.search(r'до конца (?:своего )?хода', text, re.IGNORECASE):
        kind, whose = 'end', 'target'
    elif repeat:
        kind, whose = 'repeat_save', 'target'
    elif cap:
        kind, whose = 'rounds', 'target'
    else:
        kind, whose = 'permanent', 'target'
    if repeat and kind != 'repeat_save':
        kind = 'repeat_save'
    return {'kind': kind, 'whose': whose, 'rounds': cap,
            'ability': ability, 'dc': dc}


def _conditions_in(text):
    found = []
    for condition_id, pattern in _CONDITION_RES:
        if pattern.search(text or ''):
            found.append(condition_id)
    return found


def _recharge(text):
    span = _RECHARGE_SPAN.search(text or '')
    if span:
        low, high = int(span.group(1)), int(span.group(2))
        return {'low': min(low, high), 'high': max(low, high)}
    one = _RECHARGE_ONE.search(text or '')
    if one:
        face = int(one.group(1))
        return {'low': face, 'high': face}
    return None


def _first_int(patterns, text):
    for pattern in patterns:
        match = pattern.search(text or '')
        if not match:
            continue
        for group in match.groups():
            if group:
                return int(group)
    return None


def _width_ft(text):
    match = _WIDTH_RE.search(text or '')
    if not match:
        return None
    for group in match.groups():
        if group:
            return int(group)
    return None


def _height_ft(text):
    match = _HEIGHT_RE.search(text or '')
    if not match:
        return None
    for group in match.groups():
        if group:
            return int(group)
    return None


def _place_ft(text):
    match = _WITHIN_RE.search(text or '')
    if not match:
        return None
    for group in match.groups():
        if group:
            return int(group)
    return None


def _spec(shape, size, text, *, width=None, height=None):
    spec = {
        'shape': shape,
        'size': int(size),
        'width': width,
        'height': height,
        'placed': False,
        'place_ft': None,
    }
    if shape in ('cone', 'line', 'radius'):
        return spec
    point = bool(_POINT_RE.search(text or ''))
    anchored = bool(_FROM_SELF_RE.search(text or '')) and not point
    place = _place_ft(text)
    if anchored:
        return spec
    if point or (place and place != spec['size']):
        spec['placed'] = True
        if place and place != spec['size']:
            spec['place_ft'] = place
        else:
            # «с центром в точке» без отдельной дистанции: ищем центр не дальше 120 фт.
            spec['place_ft'] = place or 120
    return spec


def parse_area(text):
    """Форма и размер области или (None, None).

    Если в тексте есть слово формы, но нет размера — (None, предупреждение).
    """
    text = text or ''
    cone = _first_int(_CONE_RES, text)
    if cone:
        return _spec('cone', cone, text), None
    line = _first_int(_LINE_RES, text)
    if line:
        return _spec('line', line, text, width=_width_ft(text) or 5), None
    cube = _first_int(_CUBE_RES, text)
    if cube:
        return _spec('cube', cube, text), None
    square = _first_int(_SQUARE_RES, text)
    if square:
        return _spec('square', square, text), None
    radius = _first_int(_RADIUS_RES, text)
    height = _height_ft(text)
    cylinder_word = bool(re.search(r'цилиндр|\bcylinder\b', text, re.IGNORECASE))
    sphere_word = bool(re.search(r'сфер|\bsphere\b', text, re.IGNORECASE))
    if radius and (cylinder_word or height):
        return _spec('cylinder', radius, text, height=height), None
    if radius and sphere_word:
        return _spec('sphere', radius, text), None
    if radius:
        return _spec('radius', radius, text), None
    within = _place_ft(text)
    if within and not sphere_word and not cylinder_word:
        return _spec('radius', within, text), None
    if _SHAPE_WORD_RE.search(text):
        return None, 'область не разобрана и остаётся текстом'
    return None, None


def _looks_like_save(text):
    return bool(_SAVE_RE.search(text or ''))


def parse_special_effect(name, desc):
    """Структура действия или (None, предупреждение).

    Отложенные эффекты («когда существо начинает ход в облаке») не исполняются:
    остаются текстом с предупреждением.
    """
    text = f'{name or ""}. {desc or ""}'
    if _DELAYED_RE.search(desc or '') and not _CONE_RE.search(desc or ''):
        if _looks_like_save(desc):
            return None, (f'эффект «{name}» срабатывает не сразу и остаётся текстом')
    save = _SAVE_RE.search(desc or '')
    if save is None:
        if re.search(r'спасброс', desc or '', re.IGNORECASE) and re.search(
                r'\bсл\s*\d+', desc or '', re.IGNORECASE):
            return None, (f'эффект «{name}» не разобран и остаётся текстом')
        return None, None
    ability = ability_of(save.group('abil'))
    dc = int(save.group('dc'))
    if not ability:
        return None, (f'эффект «{name}» не разобран и остаётся текстом')
    damage = parse_damage(desc or '')
    area, area_warning = parse_area(desc or '')
    conditions = _conditions_in(desc or '')
    if area_warning and area is None and (damage is not None or conditions or _looks_like_save(desc)):
        return None, (f'эффект «{name}»: {area_warning}')
    if damage is None and not conditions:
        return None, (f'эффект «{name}» не разобран и остаётся текстом')
    single = bool(re.search(
        r'одно существо|одну цель|нацеливается на одно|одному существу',
        desc or '', re.IGNORECASE))
    everyone = bool(re.search(r'все существа|каждое существо|каждого существа',
                              desc or '', re.IGNORECASE))
    if area is None:
        shape = 'single' if single or not everyone else 'radius'
        reach = 30
        width = height = place_ft = None
        placed = False
    else:
        shape = area['shape']
        reach = area['size']
        width = area.get('width')
        height = area.get('height')
        placed = bool(area.get('placed'))
        place_ft = area.get('place_ft')
        if single and not everyone:
            shape = 'single'
    duration = parse_duration(desc or '', ability, dc)
    supplement = (damage is None and bool(_SUPPLEMENT_RE.search(name or '')))
    immunity = bool(re.search(r'получает иммунитет', desc or '', re.IGNORECASE))
    choice = bool(re.search(r'на выбор', desc or '', re.IGNORECASE))
    return {
        'kind': 'save',
        'name': name or '',
        'ability': ability,
        'dc': dc,
        'damage': damage,
        'half_on_success': _half(desc or ''),
        'conditions': conditions,
        'duration': duration,
        'area': shape,
        'range_ft': int(reach or 5),
        'width_ft': width,
        'height_ft': height,
        'placed': placed,
        'place_ft': place_ft,
        'recharge': _recharge(text),
        'supplement': supplement,
        'immunity_on_save': immunity,
        'choice': choice,
        'replaces': not supplement,
    }, None


def parse_on_hit(text):
    """Всадники попадания: захват, спасбросок или автосостояние. Список и предупреждения."""
    text = text or ''
    riders = []
    warnings = []
    grapple = re.search(r'схвачен', text, re.IGNORECASE)
    escape = re.search(r'сл\s+высвобождени\w*\s*(\d+)', text, re.IGNORECASE)
    if grapple:
        riders.append({
            'kind': 'on_hit',
            'save': None,
            'condition': 'grappled',
            'escape_dc': int(escape.group(1)) if escape else None,
            'duration': {'kind': 'permanent', 'whose': 'target', 'rounds': None,
                         'ability': None, 'dc': None},
        })
    for save in _SAVE_RE.finditer(text):
        ability = ability_of(save.group('abil'))
        if not ability:
            continue
        window = text[save.start():save.start() + 280]
        conditions = [item for item in _conditions_in(window) if item != 'grappled']
        if not conditions:
            continue
        dc = int(save.group('dc'))
        duration = parse_duration(window, ability, dc)
        for condition_id in conditions:
            riders.append({
                'kind': 'on_hit',
                'save': {'ability': ability, 'dc': dc},
                'condition': condition_id,
                'escape_dc': None,
                'duration': duration,
            })
    if not riders:
        for condition_id in _conditions_in(text):
            if condition_id == 'grappled':
                continue
            if condition_id == 'speed_zero':
                continue
            # Урон в тексте атаки сам по себе не всадник. Берём только явное
            # состояние после «попадание», если отдельного спасброска нет.
            if not re.search(r'попадание', text, re.IGNORECASE):
                continue
            tail = re.split(r'попадание\s*:?', text, maxsplit=1, flags=re.IGNORECASE)[-1]
            if condition_id not in _conditions_in(tail):
                continue
            if _SAVE_RE.search(tail):
                continue
            riders.append({
                'kind': 'on_hit',
                'save': None,
                'condition': condition_id,
                'escape_dc': None,
                'duration': {'kind': 'permanent', 'whose': 'target', 'rounds': None,
                             'ability': None, 'dc': None},
            })
    if _looks_like_save(text) and not any(item.get('save') for item in riders) and not grapple:
        # Спасбросок есть, но ни состояния, ни захвата. Предупреждение снаружи,
        # если это не обычная атака с уроном по спасброску — такие редки в атаке.
        if not riders:
            warnings.append('эффект попадания со спасброском не разобран и остаётся текстом')
    return riders, warnings


def _rng_of(creature):
    import random
    return getattr(creature, '_rng', None) or random


def _distance(attacker, target, battle_map):
    if battle_map is not None and battle_map.get_pos(attacker) and battle_map.get_pos(target):
        return float(battle_map.distance_ft(attacker, target))
    from battle_strategies import distance_ft_between
    return float(distance_ft_between(attacker, target))


def _hostile(attacker, creature, ignore):
    if creature is attacker or not getattr(creature, 'alive', False):
        return False
    if getattr(creature, 'side', None) == getattr(attacker, 'side', None):
        return False
    side = getattr(creature, 'side', None)
    ignore = ignore or set()
    personal = getattr(attacker, 'ignore_sides', None) or set()
    if side in ignore or side in personal:
        return False
    return True


# Союзник в шаблоне «стоит» двух врагов: дыхание в своих не выпускают, пока
# врагов не заметно больше.
FRIENDLY_WEIGHT = 2.0

_DIRECTED = ('cone', 'line', 'cube', 'square')
_PLACED = ('sphere', 'cylinder', 'cube', 'square')


class Placement:
    """Выбранный шаблон: клетки, точка начала и подпись для журнала."""

    __slots__ = ('shape', 'origin', 'direction', 'cells', 'label',
                 'length_ft', 'width_ft', 'creatures')

    def __init__(self, shape, origin, direction, cells, label, length_ft, width_ft=None):
        self.shape = shape
        self.origin = origin
        self.direction = direction
        self.cells = frozenset(cells or ())
        self.label = label
        self.length_ft = length_ft
        self.width_ft = width_ft
        self.creatures = []


def _stable(creatures):
    return sorted(creatures, key=lambda creature: (
        getattr(creature, 'side', 0) or 0,
        getattr(creature, 'name', '') or '',
        id(creature)))


def _legacy_targets(attacker, effect, sides, ignore, battle_map, focus):
    """Без карты или для одной цели: враги в дистанции, ближайший или focus."""
    reach = int(effect.get('range_ft') or 5)
    found = []
    for creature in iter_creatures(sides):
        if not _hostile(attacker, creature, ignore):
            continue
        if _distance(attacker, creature, battle_map) > reach:
            continue
        found.append(creature)
    if (effect.get('area') or 'radius') == 'single':
        if focus is not None and focus in found:
            return [focus]
        if not found:
            return []
        found.sort(key=lambda creature: _distance(attacker, creature, battle_map))
        return found[:1]
    return found


def _exposed(creature, effect):
    """Есть ли существу смысл попасть под эффект: урон пройдёт или ляжет состояние."""
    from conditions import is_condition_immune
    conditions = [item for item in (effect.get('conditions') or [])
                  if not is_condition_immune(creature, item)]
    damage = effect.get('damage')
    if not damage:
        return bool(conditions)
    try:
        from combat_core import modify_damage
        final, _note = modify_damage(
            creature, 12, damage.get('damage_type') or '', magical=True)
    except (TypeError, ValueError):
        return True
    return final > 0 or bool(conditions)


def _split_sides(attacker, creatures, ignore):
    enemies, allies = [], []
    for creature in creatures:
        if creature is attacker or not getattr(creature, 'alive', False):
            continue
        if _hostile(attacker, creature, ignore):
            enemies.append(creature)
        else:
            allies.append(creature)
    return enemies, allies


def _area_phrase(effect, origin, direction):
    shape = effect.get('area') or 'radius'
    length = int(effect.get('range_ft') or 0)
    if shape == 'line':
        body = f'линия {length}×{int(effect.get("width_ft") or 5)} фт'
    elif shape == 'cylinder':
        body = f'цилиндр радиусом {length} фт'
        height = effect.get('height_ft')
        if height:
            body += f' и высотой {int(height)} фт'
    elif shape == 'sphere':
        body = f'сфера радиусом {length} фт'
    elif shape == 'radius':
        body = f'радиус {length} фт'
    elif shape == 'cube':
        body = f'куб {length} фт'
    elif shape == 'square':
        body = f'квадрат {length} фт'
    else:
        body = f'конус {length} фт'
    if direction and shape in _DIRECTED and not (
            effect.get('placed') and shape in ('sphere', 'cylinder')):
        from battle_map_model import direction_name
        body += f' на {direction_name(direction[0], direction[1])}'
    if effect.get('placed') and origin is not None and shape in _PLACED:
        body += f', центр ({_fmt_coord(origin[0])}, {_fmt_coord(origin[1])})'
    return body


def _fmt_coord(value):
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(round(number, 1))


def _cells_for(effect, origin, direction, bounds):
    from battle_map_model import template_cells
    return template_cells(
        effect.get('area'), origin, direction, effect.get('range_ft') or 0,
        effect.get('width_ft'), bounds=bounds, height_ft=effect.get('height_ft'))


def _occupants(attacker, sides, battle_map, cells):
    from battle_map_model import footprint_cells
    if not cells:
        return []
    found = []
    for creature in iter_creatures(sides):
        if creature is attacker or not getattr(creature, 'alive', False):
            continue
        if footprint_cells(battle_map, creature) & cells:
            found.append(creature)
    return _stable(found)


def _aim_directions(attacker, battle_map, sides, ignore):
    from battle_map_model import COMPASS, direction_name, footprint_center, unit_vector
    center = footprint_center(battle_map, attacker)
    raw = [(label, dx, dy) for label, dx, dy in COMPASS]
    if center is not None:
        for creature in iter_creatures(sides):
            if not _hostile(attacker, creature, ignore):
                continue
            there = footprint_center(battle_map, creature)
            if there is None:
                continue
            dx, dy = there[0] - center[0], there[1] - center[1]
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                continue
            raw.append((direction_name(dx, dy), dx, dy))
    unique, seen = [], []
    for label, dx, dy in raw:
        ux, uy = unit_vector(dx, dy)
        if any(abs(ux - sx) < 0.08 and abs(uy - sy) < 0.08 for sx, sy in seen):
            continue
        seen.append((ux, uy))
        unique.append((label, ux, uy))
    return unique


def _place_points(attacker, effect, battle_map, sides, ignore):
    from battle_map_model import point_distance_ft
    length = float(effect.get('range_ft') or 5)
    place = effect.get('place_ft')
    if not place:
        place = 120
    span = int(length / 5.0) + 2
    points = []
    seen = set()
    for creature in iter_creatures(sides):
        if not _hostile(attacker, creature, ignore):
            continue
        pos = battle_map.get_pos(creature)
        if not pos:
            continue
        cx, cy = int(round(pos[0])), int(round(pos[1]))
        for iy in range(cy - span, cy + span + 2):
            for ix in range(cx - span, cx + span + 2):
                if (ix, iy) in seen:
                    continue
                if not (0 <= ix <= battle_map.width and 0 <= iy <= battle_map.height):
                    continue
                if point_distance_ft(battle_map, attacker, (ix, iy)) > float(place) + 1e-6:
                    continue
                seen.add((ix, iy))
                points.append((ix, iy))
    return points


def _make_placement(attacker, effect, battle_map, origin, direction):
    bounds = (battle_map.width, battle_map.height)
    shape = effect.get('area') or 'radius'
    if shape == 'radius':
        from battle_map_model import emanation_cells, footprint_center
        cells = emanation_cells(
            battle_map, attacker, effect.get('range_ft') or 0, bounds=bounds)
        origin = footprint_center(battle_map, attacker)
        direction = None
    else:
        from battle_map_model import footprint_cells
        cells = _cells_for(effect, origin, direction, bounds) - footprint_cells(
            battle_map, attacker)
    return Placement(
        shape, origin, direction, cells,
        _area_phrase(effect, origin, direction),
        int(effect.get('range_ft') or 0),
        effect.get('width_ft'))


def iter_placements(attacker, effect, sides, ignore, battle_map):
    """Варианты направления или центра, которые исполнитель сравнивает."""
    from battle_map_model import aim_origin, cube_origin, footprint_center
    if battle_map is None or battle_map.get_pos(attacker) is None:
        return
    shape = effect.get('area') or 'radius'
    pos = battle_map.get_pos(attacker)
    size = battle_map.cells_of(attacker)
    length = float(effect.get('range_ft') or 0)
    if shape == 'radius' or (shape in ('sphere', 'cylinder') and not effect.get('placed')):
        center = footprint_center(battle_map, attacker)
        yield _make_placement(attacker, effect, battle_map, center, None)
        return
    if shape in ('cone', 'line') or (shape in ('cube', 'square') and not effect.get('placed')):
        for _label, dx, dy in _aim_directions(attacker, battle_map, sides, ignore):
            edge = aim_origin(pos, size, (dx, dy))
            origin = cube_origin(edge, (dx, dy), length) if shape in ('cube', 'square') else edge
            yield _make_placement(attacker, effect, battle_map, origin, (dx, dy))
        return
    anchor = footprint_center(battle_map, attacker) or pos
    for point in _place_points(attacker, effect, battle_map, sides, ignore):
        dx, dy = point[0] - anchor[0], point[1] - anchor[1]
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            dx, dy = 1.0, 0.0
        origin = point
        if shape in ('cube', 'square'):
            origin = cube_origin(point, (dx, dy), length)
        yield _make_placement(attacker, effect, battle_map, origin, (dx, dy))


def best_placement(attacker, effect, sides, ignore, battle_map, focus=None):
    """Направление или центр с наибольшей пользой: враги минус союзники с весом.

    Пустой результат — бить область невыгодно (никого или слишком много своих).
    """
    if effect is None or battle_map is None or battle_map.get_pos(attacker) is None:
        return None
    if (effect.get('area') or 'radius') == 'single':
        return None
    best = None
    best_key = None
    choice = bool(effect.get('choice'))
    for placement in iter_placements(attacker, effect, sides, ignore, battle_map):
        creatures = _occupants(attacker, sides, battle_map, placement.cells)
        enemies, allies = _split_sides(attacker, creatures, ignore)
        enemies = [creature for creature in enemies if _exposed(creature, effect)]
        allies = [creature for creature in allies if _exposed(creature, effect)]
        if not enemies:
            continue
        if choice:
            score = float(len(enemies))
        else:
            score = len(enemies) - FRIENDLY_WEIGHT * len(allies)
        if score <= 0:
            continue
        focus_hit = 1 if focus in enemies else 0
        key = (score, len(enemies), focus_hit, -len(allies))
        if best_key is None or key > best_key:
            best_key = key
            placement.creatures = creatures
            best = placement
    return best


def aim_at(attacker, effect, battle_map, point, sides=None, ignore=None):
    """Шаблон от клика: направление для конуса и линии, центр для сферы и куба."""
    from battle_map_model import (aim_origin, cube_origin, footprint_center,
                                  nearest_intersection, point_distance_ft, unit_vector)
    if battle_map is None or effect is None or battle_map.get_pos(attacker) is None:
        return None
    shape = effect.get('area') or 'radius'
    center = footprint_center(battle_map, attacker)
    px, py = float(point[0]), float(point[1])
    dx, dy = px - center[0], py - center[1]
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        dx, dy = 1.0, 0.0
    pos = battle_map.get_pos(attacker)
    size = battle_map.cells_of(attacker)
    length = float(effect.get('range_ft') or 0)
    if shape == 'radius' or (shape in ('sphere', 'cylinder') and not effect.get('placed')):
        placement = _make_placement(attacker, effect, battle_map, center, None)
    elif shape in ('cone', 'line') or (shape in ('cube', 'square') and not effect.get('placed')):
        edge = aim_origin(pos, size, (dx, dy))
        origin = cube_origin(edge, (dx, dy), length) if shape in ('cube', 'square') else edge
        placement = _make_placement(attacker, effect, battle_map, origin, (dx, dy))
    else:
        place = float(effect.get('place_ft') or 120)
        if point_distance_ft(battle_map, attacker, (px, py)) > place + 1e-6:
            reach = place / 5.0
            ux, uy = unit_vector(dx, dy)
            px = center[0] + ux * reach
            py = center[1] + uy * reach
        origin = nearest_intersection((px, py))
        if shape in ('cube', 'square'):
            origin = cube_origin(origin, (dx, dy), length)
        placement = _make_placement(attacker, effect, battle_map, origin, (dx, dy))
    if sides is not None:
        placement.creatures = _occupants(attacker, sides, battle_map, placement.cells)
    return placement


def resolve_targets(attacker, effect, sides, ignore, battle_map, focus=None, *,
                    placement=None, include=None):
    """Кого накрывает эффект. placement — уже выбранный шаблон (ручной прицел)."""
    shape = (effect or {}).get('area') or 'radius'
    if (effect is None or battle_map is None or battle_map.get_pos(attacker) is None
            or shape == 'single'):
        return _legacy_targets(attacker, effect, sides, ignore, battle_map, focus), None
    if placement is None:
        placement = best_placement(attacker, effect, sides, ignore, battle_map, focus)
    if placement is None:
        return [], None
    creatures = _occupants(attacker, sides, battle_map, placement.cells)
    if effect.get('choice'):
        if include is not None:
            wanted = set(include)
            creatures = [creature for creature in creatures if creature in wanted]
        else:
            creatures = [creature for creature in creatures
                         if _hostile(attacker, creature, ignore)]
    return creatures, placement


def targets_for(attacker, effect, sides, ignore, battle_map, focus=None):
    """Враги, которых эффект заденет. Союзники в выбор выгоды не входят."""
    creatures, _placement = resolve_targets(
        attacker, effect, sides, ignore, battle_map, focus=focus)
    return [creature for creature in creatures if _hostile(attacker, creature, ignore)]


def _roll_damage(attacker, damage):
    if not damage:
        return 0
    rng = _rng_of(attacker)
    sides = int(str(damage.get('dice_type') or 'd6').split('d')[-1] or 6)
    count = max(0, int(damage.get('dice_count') or 0))
    modifier = int(damage.get('modifier') or 0)
    return sum(rng.randint(1, max(1, sides)) for _ in range(max(0, count))) + modifier


def average_damage(damage):
    if not damage:
        return 0.0
    sides = int(str(damage.get('dice_type') or 'd6').split('d')[-1] or 6)
    count = int(damage.get('dice_count') or 0)
    return count * (sides + 1) / 2.0 + int(damage.get('modifier') or 0)


def _disabling(conditions):
    return any(item in HARD_DISABLE for item in conditions or [])


def _event(kind, text, attacker, target, round_no, **kwargs):
    from combat_log import CombatEvent
    payload = dict(
        kind=kind, text=text, round=round_no,
        actor=getattr(attacker, 'name', None),
        actor_id=id(attacker) if attacker is not None else None,
        actor_side=getattr(attacker, 'side', None) if attacker is not None else None,
    )
    if target is not None:
        payload.update(
            target=getattr(target, 'name', None),
            target_id=id(target),
            target_side=getattr(target, 'side', None),
        )
    payload.update(kwargs)
    return CombatEvent(**payload)


def _already_from(attacker, target, condition_id):
    if is_condition_immune(target, condition_id):
        return True
    uid = creature_uid(attacker)
    for item in active_conditions(target):
        if item.get('id') == condition_id and item.get('source_uid') == uid:
            return True
    return False


def _release_events(source, sides, round_no, events, actor=None):
    for creature, item in release_grapples_from(source, sides):
        events.append(_event(
            'condition',
            describe_removed(creature, item, 'источник не может держать'),
            actor or source, creature, round_no,
            result='removed', condition='grappled'))


def _area_payload(placement, targets):
    if placement is None:
        return {}
    origin = placement.origin
    return {
        'reason': placement.label,
        'area_cells': [tuple(cell) for cell in sorted(placement.cells)],
        'area_origin': (tuple(origin) if origin is not None else None),
        'area_ids': [id(creature) for creature in targets],
    }


def execute_effect(attacker, effect, sides, ignore, battle_map, *,
                   round_no=None, focus=None, legendary=False, lair=False,
                   placement=None, include=None):
    """Спасбросок по целям области. Возвращает CombatEvent.

    placement задаёт готовый шаблон (ручной прицел). Без него направление
    и центр выбираются так, чтобы задеть больше врагов, чем союзников.
    """
    from combat_core import modify_damage

    events = []
    if not effect or not getattr(attacker, 'alive', False):
        return events
    targets, placement = resolve_targets(
        attacker, effect, sides, ignore, battle_map, focus=focus,
        placement=placement, include=include)
    title = effect.get('name') or 'эффект'
    area_bits = _area_payload(placement, targets)
    note = area_bits.get('reason')
    if not targets:
        events.append(_event(
            'save', f'{attacker.name} не находит целей для «{title}»',
            attacker, None, round_no, result='no_target', action=title,
            legendary=legendary, reason=note, **{
                key: area_bits[key] for key in ('area_cells', 'area_origin')
                if key in area_bits}))
        return events
    raw = _roll_damage(attacker, effect.get('damage')) if effect.get('damage') else 0
    names = ', '.join(creature.name for creature in targets)
    label = note or f'{effect.get("area") or "область"} {effect.get("range_ft")} фт'
    header = f'{attacker.name} применяет «{title}» ({label}): {names}'
    if lair:
        header = f'🕳 {attacker.name} — действие логова «{title}» ({label}): {names}'
    elif legendary:
        header = f'👑 {header}'
    events.append(_event(
        'save', header, attacker, None, round_no, action=title,
        legendary=legendary, result='area', **area_bits))
    conditions = list(effect.get('conditions') or [])
    disabling = _disabling(conditions)
    half = bool(effect.get('half_on_success'))
    for target in targets:
        bag = getattr(target, 'save_immunities', None) or []
        if effect.get('immunity_on_save') and title in bag:
            continue
        if (conditions and not effect.get('damage')
                and all(_already_from(attacker, target, item) for item in conditions)):
            continue
        dtype = (effect.get('damage') or {}).get('damage_type') or ''
        if effect.get('damage'):
            fail_final, _fail_note = modify_damage(target, raw, dtype, magical=True)
            success_raw = raw // 2 if half else 0
            success_final = (modify_damage(target, success_raw, dtype, magical=True)[0]
                             if success_raw else 0)
        else:
            fail_final = success_final = 0
        before = getattr(target, 'hp', None)
        roll = saving_throw(
            target, effect.get('ability') or 'dex', effect.get('dc') or 10,
            disabling=disabling, damage_fail=fail_final,
            damage_success=success_final)
        dealt_raw = (raw // 2 if half else 0) if roll.success else raw
        final = dealt_raw
        note_dmg = ''
        parts = []
        if effect.get('damage') and dealt_raw:
            final, note_dmg = modify_damage(
                target, dealt_raw, effect['damage'].get('damage_type') or '',
                magical=True)
            target.take_damage(final)
            from combat_log import DamagePart
            parts.append(DamagePart(
                effect['damage'].get('damage_type') or '', dealt_raw, final, note_dmg, False))
        result = 'success' if roll.success else 'fail'
        text = save_text(target, roll, title=title)
        if effect.get('damage'):
            shown = 'половину' if roll.success and half else 'полный урон'
            text += f'. {final} урона ({shown}){note_dmg}'
        events.append(_event(
            'save', text, attacker, target, round_no,
            result=result, action=title, natural=roll.natural,
            naturals=list(roll.naturals), modifier=roll.modifier,
            attack_total=roll.total, dc=roll.dc, ac=roll.dc,
            save_ability=roll.ability, advantage=roll.advantage,
            resistance_used=roll.resistance_used, legendary=legendary,
            damages=parts, hp_before=before, hp_after=getattr(target, 'hp', None),
            max_hp=getattr(target, 'max_hp', None),
            condition=(conditions[0] if conditions else None),
            area_cells=area_bits.get('area_cells') or [],
            area_origin=area_bits.get('area_origin')))
        if roll.success and effect.get('immunity_on_save'):
            _grant_immunity(target, title)
        if not roll.success and getattr(target, 'alive', False):
            _grant_conditions(attacker, target, effect, conditions, round_no, events, sides)
        if not getattr(target, 'alive', False):
            events.append(_event(
                'death', f'☠️ {target.name} УНИЧТОЖЕН!', attacker, target, round_no,
                result='death', action=title, legendary=legendary,
                hp_before=before, hp_after=getattr(target, 'hp', None),
                max_hp=getattr(target, 'max_hp', None)))
            _release_events(target, sides, round_no, events, actor=attacker)
    return events


def _grant_immunity(target, key):
    if not key:
        return
    bag = getattr(target, 'save_immunities', None)
    if not isinstance(bag, list):
        try:
            target.save_immunities = []
            bag = target.save_immunities
        except (AttributeError, TypeError):
            return
    if key not in bag:
        bag.append(key)


def _grant_conditions(attacker, target, effect, conditions, round_no, events, sides):
    key = effect.get('name') if effect.get('immunity_on_save') else None
    for condition_id in conditions or []:
        if is_condition_immune(target, condition_id):
            events.append(_event(
                'condition',
                f'{target.name} невосприимчив к состоянию «{condition_name(condition_id)}»',
                attacker, target, round_no, result='immune', condition=condition_id,
                action=effect.get('name')))
            continue
        stored = apply_condition(
            target, condition_id, source=attacker, duration=effect.get('duration'),
            immunity_key=key, note=effect.get('name') or '')
        if stored is None:
            continue
        events.append(_event(
            'condition', describe_applied(target, stored), attacker, target, round_no,
            result='applied', condition=condition_id, action=effect.get('name')))
    if any(has_condition(target, item) for item in (
            'paralyzed', 'stunned', 'petrified', 'unconscious', 'incapacitated')):
        _release_events(target, sides, round_no, events, actor=attacker)


def apply_on_hit(attacker, target, attack, sides, round_no, legendary=False):
    """Всадники после попадания по ещё живому существу."""
    events = []
    if target is None or not getattr(target, 'alive', False):
        return events
    for rider in getattr(attack, 'riders', None) or []:
        condition_id = rider.get('condition')
        if not condition_id:
            continue
        save = rider.get('save')
        if save:
            disabling = condition_id in HARD_DISABLE
            roll = saving_throw(
                target, save.get('ability') or 'con', save.get('dc') or 10,
                disabling=disabling, damage_fail=0, damage_success=0)
            events.append(_event(
                'save', save_text(target, roll, title=getattr(attack, 'name', None)),
                attacker, target, round_no, result='success' if roll.success else 'fail',
                action=getattr(attack, 'name', None), natural=roll.natural,
                naturals=list(roll.naturals), modifier=roll.modifier,
                attack_total=roll.total, dc=roll.dc, ac=roll.dc,
                save_ability=roll.ability, advantage=roll.advantage,
                resistance_used=roll.resistance_used, legendary=legendary,
                condition=condition_id))
            if roll.success:
                continue
        if is_condition_immune(target, condition_id):
            events.append(_event(
                'condition',
                f'{target.name} невосприимчив к состоянию «{condition_name(condition_id)}»',
                attacker, target, round_no, result='immune', condition=condition_id,
                action=getattr(attack, 'name', None), legendary=legendary))
            continue
        duration = rider.get('duration')
        if rider.get('escape_dc') and isinstance(duration, dict):
            duration = dict(duration)
            duration['escape_dc'] = rider.get('escape_dc')
        stored = apply_condition(
            target, condition_id, source=attacker, duration=duration,
            escape_dc=rider.get('escape_dc'),
            note=getattr(attack, 'name', '') or '')
        if stored is None:
            continue
        events.append(_event(
            'condition', describe_applied(target, stored), attacker, target, round_no,
            result='applied', condition=condition_id,
            action=getattr(attack, 'name', None), legendary=legendary))
    return events


def ensure_recharge(creature):
    state = getattr(creature, 'recharge_state', None)
    if not isinstance(state, dict):
        state = {}
        try:
            creature.recharge_state = state
        except (AttributeError, TypeError):
            return {}
    for action in list(getattr(creature, 'special_actions', None) or []):
        if not isinstance(action, dict):
            continue
        effect = action.get('effect') or {}
        recharge = effect.get('recharge')
        if not recharge:
            continue
        name = action.get('name') or ''
        if name and name not in state:
            state[name] = {'low': int(recharge['low']), 'high': int(recharge['high']),
                           'ready': True}
    return state


def recharge_ready(creature, name):
    state = ensure_recharge(creature)
    slot = state.get(name)
    if slot is None:
        return True
    return bool(slot.get('ready', True))


def consume_recharge(creature, name):
    state = ensure_recharge(creature)
    if name in state:
        state[name]['ready'] = False


def roll_recharges(creature, round_no=None):
    """В начале хода: неготовое дыхание кидает d6. Уже готовое не кидается."""
    events = []
    state = ensure_recharge(creature)
    rng = _rng_of(creature)
    for name, slot in state.items():
        if slot.get('ready'):
            continue
        face = rng.randint(1, 6)
        ready = int(slot['low']) <= face <= int(slot['high'])
        slot['ready'] = ready
        if ready:
            text = (f'{creature.name}: перезарядка «{name}» — d6 {face}, снова готово')
            result = 'ready'
        else:
            text = (f'{creature.name}: перезарядка «{name}» — d6 {face}, '
                    f'нужно {slot["low"]}–{slot["high"]}')
            result = 'not_ready'
        events.append(_event(
            'recharge', text, creature, None, round_no, result=result,
            action=name, natural=face))
    return events


def _actions(creature):
    found = []
    for action in list(getattr(creature, 'special_actions', None) or []):
        if isinstance(action, dict) and isinstance(action.get('effect'), dict):
            found.append(action)
    return found


def opening_effects(creature):
    """Ужасающее присутствие, взгляды и бонусные действия: не заменяют атаку."""
    found = [action['effect'] for action in _actions(creature)
             if action['effect'].get('supplement')]
    for action in list(getattr(creature, 'bonus_actions', None) or []):
        effect = action.get('effect') if isinstance(action, dict) else None
        if isinstance(effect, dict):
            found.append(effect)
    return found


def replacing_effect(creature):
    """Дыхание и прочие действия вместо атак. None, если перезарядка не готова."""
    best = None
    for action in _actions(creature):
        effect = action['effect']
        if not effect.get('replaces'):
            continue
        if effect.get('recharge') and not recharge_ready(creature, action.get('name')):
            continue
        if effect.get('damage') or effect.get('recharge'):
            return effect
        if best is None:
            best = effect
    return best


def should_replace_attacks(attacker, effect, sides, ignore, battle_map, focus):
    """Дыхание бьём, когда кто-то в зоне (с учётом шага). Прочий контроль — если
    цель ещё не под этим жёстким состоянием. Сбивание с ног само по себе атаку
    не подменяет: в этом симуляторе цель встаёт в свой ход раньше, чем преимущество
    успевает сыграть.
    """
    if effect is None:
        return False
    if effect.get('damage') or (effect.get('area') or '') not in ('single', ''):
        if battle_map is not None and battle_map.get_pos(attacker) is not None:
            if best_placement(attacker, effect, sides, ignore, battle_map, focus) is not None:
                return True
        reach = int(effect.get('range_ft') or 5)
        try:
            step = effective_speed(attacker)
        except (TypeError, ValueError):
            step = int(getattr(attacker, 'speed', 0) or 0)
        limit = reach + max(0, int(step))
        for creature in iter_creatures(sides):
            if _hostile(attacker, creature, ignore) and _distance(
                    attacker, creature, battle_map) <= limit:
                return True
        return False
    conditions = effect.get('conditions') or []
    if not any(item in HARD_DISABLE for item in conditions):
        return False
    if focus is None:
        return False
    return not all(has_condition(focus, item) for item in conditions)


def run_lair(creature, sides, ignore, battle_map, round_no):
    """Одно разбираемое действие логова за раунд, по кругу. Не инициатива 20:
    ход логова считается в начале раунда.
    """
    block = getattr(creature, 'lair_actions', None) or {}
    items = list(block.get('actions') or [])
    parsed = []
    warnings = []
    for item in items:
        if isinstance(item, dict):
            name, desc = item.get('name') or 'Логово', item.get('desc') or ''
        else:
            text = str(item or '').strip()
            if not text:
                continue
            name, _, desc = text.partition('.')
            name, desc = name.strip() or 'Логово', desc.strip() or text
        if _DELAYED_RE.search(desc):
            warnings.append(name)
            continue
        effect, warning = parse_special_effect(name, desc)
        if effect:
            parsed.append(effect)
        elif warning:
            warnings.append(name)
    events = []
    if not parsed:
        if warnings and not getattr(creature, 'lair_warned', False):
            try:
                creature.lair_warned = True
            except (AttributeError, TypeError):
                pass
            events.append(_event(
                'lair',
                f'{creature.name}: действия логова остаются текстом ({", ".join(warnings[:3])})',
                creature, None, round_no, result='unparsed'))
        return events
    index = int(getattr(creature, 'lair_index', 0) or 0) % len(parsed)
    try:
        creature.lair_index = index + 1
    except (AttributeError, TypeError):
        pass
    events.extend(execute_effect(
        creature, parsed[index], sides, ignore, battle_map,
        round_no=round_no, lair=True))
    return events


def on_creature_down(creature, sides, round_no=None, actor=None):
    """Смерть или вывод из строя: чужие схватки этого существа спадают."""
    events = []
    _release_events(creature, sides, round_no, events, actor=actor or creature)
    return events


def legendary_effects(creature):
    block = getattr(creature, 'legendary_actions', None) or {}
    found = []
    for option in block.get('options') or []:
        effect = option.get('effect') if isinstance(option, dict) else None
        if isinstance(effect, dict):
            found.append(option)
    return found
