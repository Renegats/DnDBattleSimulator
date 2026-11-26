"""Состояния 5e и спасброски. Без привязки к интерфейсу.

Натуральные 20 и 1 на спасброске ничего не значат (RAW). Преимущество и помеха
на броске атаки — два d20; если есть и то и другое, они гасятся и кидается
один d20.
"""
import random
import uuid

ABILITY_RU = {
    'str': 'Силы',
    'dex': 'Ловкости',
    'con': 'Телосложения',
    'int': 'Интеллекта',
    'wis': 'Мудрости',
    'cha': 'Харизмы',
}

ABILITY_WORDS = {
    'str': ('сил', 'str'),
    'dex': ('лов', 'dex'),
    'con': ('тел', 'con'),
    'int': ('инт', 'int'),
    'wis': ('мдр', 'муд', 'wis'),
    'cha': ('хар', 'cha'),
}

# Слова из «Иммунитет к состоянию» на dnd.su.
IMMUNITY_WORDS = {
    'blinded': ('ослеп', 'blind'),
    'charmed': ('очарован', 'charm'),
    'deafened': ('оглох', 'глухот', 'deaf'),
    'frightened': ('испуг', 'fright'),
    'grappled': ('схват', 'захват', 'grappl'),
    'incapacitated': ('недееспособ', 'incapac'),
    'invisible': ('невидим', 'invis'),
    'paralyzed': ('паралич', 'paralyz'),
    'petrified': ('окамен', 'petrif'),
    'poisoned': ('отрав', 'poison'),
    'prone': ('сбиван', 'prone'),
    'restrained': ('опутан', 'удержан', 'restrain'),
    'stunned': ('ошелом', 'stun'),
    'unconscious': ('без сознания', 'бессознат', 'unconscious'),
    'exhaustion': ('истощен', 'истощён', 'exhaust'),
    'speed_zero': ('скорость 0',),
}

SPEED_ZERO = frozenset({
    'grappled', 'restrained', 'paralyzed', 'petrified', 'stunned',
    'unconscious', 'speed_zero',
})
INCAPACITATED = frozenset({
    'incapacitated', 'paralyzed', 'petrified', 'stunned', 'unconscious',
})
AUTO_FAIL_STR_DEX = frozenset({
    'paralyzed', 'petrified', 'stunned', 'unconscious',
})
HARD_DISABLE = frozenset({
    'paralyzed', 'petrified', 'stunned', 'unconscious', 'incapacitated',
    'restrained', 'frightened',
})

# id, русское имя, короткая плашка, цвет, прятать ли из ручного меню.
CATALOG = (
    ('blinded', 'ослеплён', 'ОСЛ', '#7f8c8d', False),
    ('charmed', 'очарован', 'ОЧ', '#e84393', False),
    ('deafened', 'оглохший', 'ГЛХ', '#95a5a6', False),
    ('frightened', 'испуган', 'ИСП', '#8e44ad', False),
    ('grappled', 'схвачен', 'СХВ', '#d35400', False),
    ('incapacitated', 'недееспособен', 'НД', '#2c3e50', False),
    ('invisible', 'невидимый', 'НВД', '#16a085', False),
    ('paralyzed', 'парализован', 'ПАР', '#2980b9', False),
    ('petrified', 'окаменевший', 'КАМ', '#7f8c8d', False),
    ('poisoned', 'отравлен', 'ЯД', '#27ae60', False),
    ('prone', 'сбит с ног', 'ЛЕЖ', '#b9770e', False),
    ('restrained', 'опутан', 'ОПУ', '#6e2c00', False),
    ('stunned', 'ошеломлён', 'ОШ', '#1a5276', False),
    ('unconscious', 'без сознания', 'БС', '#1c2833', False),
    ('exhaustion', 'истощение', 'ИС', '#922b21', False),
    # Не состояние PHB: «скорость становится 0» из дыхания и похожих эффектов.
    ('speed_zero', 'скорость 0', '0', '#34495e', True),
)

_BY_ID = {row[0]: row for row in CATALOG}
MANUAL_IDS = tuple(row[0] for row in CATALOG if not row[4] and row[0] != 'exhaustion')


def catalog_row(condition_id):
    return _BY_ID.get(condition_id)


def condition_name(condition_id):
    row = _BY_ID.get(condition_id)
    return row[1] if row else str(condition_id or '')


def condition_short(condition_id, level=None):
    row = _BY_ID.get(condition_id)
    if row is None:
        return '?'
    if condition_id == 'exhaustion' and level:
        return f'{row[2]}{int(level)}'
    return row[2]


def condition_color(condition_id):
    row = _BY_ID.get(condition_id)
    return row[3] if row else '#555555'


def ability_of(label):
    low = str(label or '').strip().lower()
    if not low:
        return None
    for key, words in ABILITY_WORDS.items():
        if any(low.startswith(word) for word in words):
            return key
    return None


def creature_uid(creature):
    if creature is None:
        return None
    uid = getattr(creature, 'uid', None)
    if not uid:
        uid = uuid.uuid4().hex
        try:
            creature.uid = uid
        except (AttributeError, TypeError):
            return None
    return uid


def active_conditions(creature):
    raw = getattr(creature, 'conditions', None) or []
    if not isinstance(raw, list):
        return []
    return raw


def _ids(creature):
    return {item.get('id') for item in active_conditions(creature) if isinstance(item, dict)}


def has_condition(creature, condition_id):
    return condition_id in _ids(creature)


def exhaustion_level(creature):
    for item in active_conditions(creature):
        if isinstance(item, dict) and item.get('id') == 'exhaustion':
            try:
                return int(item.get('level') or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def is_incapacitated(creature):
    if not getattr(creature, 'alive', True):
        return True
    if _ids(creature) & INCAPACITATED:
        return True
    return exhaustion_level(creature) >= 6


def effective_speed(creature):
    try:
        speed = int(getattr(creature, 'speed', 30) or 0)
    except (TypeError, ValueError):
        speed = 30
    if _ids(creature) & SPEED_ZERO:
        return 0
    level = exhaustion_level(creature)
    if level >= 5:
        return 0
    if level >= 2:
        speed //= 2
    return max(0, speed)


def effective_max_hp(creature):
    try:
        cap = int(getattr(creature, 'max_hp', 0) or 0)
    except (TypeError, ValueError):
        cap = 0
    if exhaustion_level(creature) >= 4:
        cap = max(1, cap // 2)
    return cap


def is_condition_immune(creature, condition_id):
    if condition_id == 'poisoned' and has_condition(creature, 'petrified'):
        return True
    blob = ' '.join(str(item).lower() for item in
                    (getattr(creature, 'condition_immunities', None) or []))
    if not blob:
        return False
    for needle in IMMUNITY_WORDS.get(condition_id, ()):
        if needle in blob:
            return True
    return False


def _same_source(cond, creature):
    if creature is None or not isinstance(cond, dict):
        return False
    uid = getattr(creature, 'uid', None)
    if uid and cond.get('source_uid') == uid:
        return True
    name = getattr(creature, 'name', None)
    return bool(name) and cond.get('source_uid') is None and cond.get('source_name') == name


def find_condition(creature, condition_id, source=None):
    for item in active_conditions(creature):
        if not isinstance(item, dict) or item.get('id') != condition_id:
            continue
        if source is not None and not _same_source(item, source):
            continue
        return item
    return None


def permanent_duration():
    return {'kind': 'permanent', 'whose': 'target', 'rounds': None,
            'ability': None, 'dc': None}


def duration_text(duration, condition_id=None):
    duration = duration or {}
    kind = duration.get('kind') or 'permanent'
    rounds = duration.get('rounds')
    ability = ABILITY_RU.get(duration.get('ability') or '', '')
    dc = duration.get('dc')
    if kind == 'repeat_save':
        base = 'повтор спасброска в конце хода'
        if ability and dc:
            base = f'повтор спасброска {ability} Сл {dc} в конце хода'
        if rounds:
            return f'{base}, ещё до {rounds} раунд.'
        return base
    if kind == 'rounds':
        return f'{int(rounds or 0)} раунд.'
    if kind == 'start':
        who = 'источника' if duration.get('whose') == 'source' else 'цели'
        return f'до начала хода {who}'
    if kind == 'end':
        who = 'источника' if duration.get('whose') == 'source' else 'цели'
        return f'до конца хода {who}'
    if condition_id == 'grappled' and duration.get('escape_dc'):
        return f'Сл высвобождения {duration.get("escape_dc")}'
    return 'пока не снято'


def _copy_duration(duration, escape_dc=None):
    base = permanent_duration()
    if isinstance(duration, dict):
        base.update(duration)
    if escape_dc is not None:
        base['escape_dc'] = escape_dc
    return base


def _stackable(condition_id):
    return condition_id in ('frightened', 'charmed', 'grappled')


def apply_condition(target, condition_id, *, source=None, duration=None,
                    level=None, note='', immunity_key=None, escape_dc=None):
    """Вешает состояние. None, если иммунитет или состояние неизвестно.

    Одинаковое состояние от того же источника обновляет длительность.
    Истощение копится уровнем. Без сознания роняет существо (prone),
    если к сбиванию с ног нет иммунитета.
    """
    if target is None or not catalog_row(condition_id):
        return None
    if not getattr(target, 'alive', True) and condition_id != 'unconscious':
        return None
    if is_condition_immune(target, condition_id):
        return None
    if not hasattr(target, 'conditions') or not isinstance(target.conditions, list):
        try:
            target.conditions = []
        except (AttributeError, TypeError):
            return None

    if condition_id == 'exhaustion':
        gain = 1 if level is None else int(level)
        current = find_condition(target, 'exhaustion')
        if current is None:
            current = {
                'id': 'exhaustion',
                'level': 0,
                'source_uid': creature_uid(source),
                'source_name': getattr(source, 'name', None),
                'duration': permanent_duration(),
                'note': note or '',
                'immunity_key': immunity_key,
            }
            target.conditions.append(current)
        current['level'] = max(0, min(6, int(current.get('level') or 0) + gain))
        _after_exhaustion(target)
        return current

    source_uid = creature_uid(source)
    existing = None
    for item in target.conditions:
        if item.get('id') != condition_id:
            continue
        if _stackable(condition_id):
            if source_uid and item.get('source_uid') == source_uid:
                existing = item
                break
            continue
        existing = item
        break
    payload = {
        'id': condition_id,
        'level': None,
        'source_uid': source_uid,
        'source_name': getattr(source, 'name', None),
        'duration': _copy_duration(duration, escape_dc),
        'note': note or '',
        'immunity_key': immunity_key,
    }
    if existing is None:
        target.conditions.append(payload)
        stored = payload
    else:
        existing.update(payload)
        stored = existing
    if condition_id == 'unconscious':
        apply_condition(target, 'prone', source=source,
                        duration=permanent_duration(), note='падает ничком')
    return stored


def remove_condition(target, condition_id=None, *, source=None, cond=None, reason=''):
    """Снимает одно состояние или все с указанным id. Возвращает снятые записи."""
    items = active_conditions(target)
    if not items:
        return []
    removed = []
    kept = []
    for item in items:
        drop = False
        if cond is not None and item is cond:
            drop = True
        elif condition_id and item.get('id') == condition_id:
            if source is None or _same_source(item, source):
                drop = True
        if drop:
            if reason:
                item['removed_because'] = reason
            removed.append(item)
        else:
            kept.append(item)
    if removed:
        target.conditions = kept
    for item in removed:
        key = item.get('immunity_key')
        if key:
            bag = getattr(target, 'save_immunities', None)
            if not isinstance(bag, list):
                try:
                    target.save_immunities = []
                    bag = target.save_immunities
                except (AttributeError, TypeError):
                    bag = None
            if isinstance(bag, list) and key not in bag:
                bag.append(key)
    return removed


def clear_conditions(target):
    removed = list(active_conditions(target))
    if hasattr(target, 'conditions'):
        target.conditions = []
    return removed


def _after_exhaustion(target):
    cap = effective_max_hp(target)
    if getattr(target, 'hp', 0) > cap:
        target.hp = cap
        notify = getattr(target, 'notify', None)
        if notify:
            notify()
    if exhaustion_level(target) >= 6 and getattr(target, 'alive', False):
        target.hp = 0
        target.alive = False
        clear_conditions(target)
        notify = getattr(target, 'notify', None)
        if notify:
            notify()


def set_exhaustion(target, level):
    """Ставит точный уровень истощения. 0 снимает состояние."""
    level = max(0, min(6, int(level or 0)))
    remove_condition(target, 'exhaustion')
    if level <= 0:
        return None
    stored = apply_condition(target, 'exhaustion', level=0)
    if stored is None:
        return None
    stored['level'] = level
    _after_exhaustion(target)
    return stored


def release_grapples_from(source, sides):
    """Схватка спадает, если источник мёртв или недееспособен. Список снятых."""
    if source is None or sides is None:
        return []
    if getattr(source, 'alive', False) and not (_ids(source) & INCAPACITATED):
        return []
    removed = []
    for creature in iter_creatures(sides):
        if creature is source:
            continue
        for item in list(active_conditions(creature)):
            if item.get('id') == 'grappled' and _same_source(item, source):
                gone = remove_condition(
                    creature, cond=item, reason='источник не может держать')
                removed.extend((creature, piece) for piece in gone)
    return removed


def iter_creatures(sides):
    for side in sides or []:
        for creature in side or []:
            yield creature


def auto_fail_save(creature, ability):
    if ability in ('str', 'dex') and (_ids(creature) & AUTO_FAIL_STR_DEX):
        return True
    return False


def save_disadvantage(creature, ability):
    if exhaustion_level(creature) >= 3:
        return True
    if ability == 'dex' and has_condition(creature, 'restrained'):
        return True
    return False


def ability_modifier(creature, ability):
    mods = getattr(creature, 'ability_mods', None) or {}
    if isinstance(mods, dict) and mods.get(ability) is not None:
        try:
            return int(mods[ability])
        except (TypeError, ValueError):
            pass
    scores = getattr(creature, 'ability_scores', None) or {}
    raw = scores.get(ability) if isinstance(scores, dict) else None
    if raw is None:
        return 0
    try:
        return (int(raw) - 10) // 2
    except (TypeError, ValueError):
        return 0


def save_bonus(creature, ability):
    """Бонус спасброска: число из статблока, если спас броска указан, иначе мод."""
    saves = getattr(creature, 'saves', None) or {}
    if isinstance(saves, dict):
        for key, value in saves.items():
            if ability_of(key) != ability:
                continue
            text = str(value).replace('+', '').replace(' ', '')
            try:
                return int(text)
            except ValueError:
                break
    return ability_modifier(creature, ability)


def legendary_resistance_remaining(creature):
    block = getattr(creature, 'legendary_resistance', None)
    if not isinstance(block, dict):
        return 0
    current = getattr(creature, 'legendary_resistance_remaining', None)
    if current is None:
        current = int(block.get('count') or 0)
        try:
            creature.legendary_resistance_remaining = current
        except (AttributeError, TypeError):
            return int(current)
    try:
        return int(current)
    except (TypeError, ValueError):
        return 0


def worth_legendary_resistance(creature, *, disabling, damage_fail, damage_success):
    """Простая эвристика: жёсткое состояние или большой урон, если успех реально лучше."""
    try:
        hp = int(getattr(creature, 'hp', 0) or 0)
    except (TypeError, ValueError):
        hp = 0
    damage_fail = max(0, int(damage_fail or 0))
    damage_success = max(0, int(damage_success or 0))
    if damage_success >= hp > 0 and not disabling:
        return False
    if disabling:
        return True
    if damage_fail <= 0:
        return False
    if hp > 0 and hp - damage_fail <= 0 and damage_success < hp:
        return True
    if damage_fail >= max(10, hp // 2) and damage_success < damage_fail:
        return True
    return False


class SaveRoll:
    """Результат спасброска. success уже учитывает легендарное сопротивление."""

    __slots__ = ('ability', 'natural', 'naturals', 'modifier', 'total', 'dc',
                 'success', 'auto_fail', 'advantage', 'resistance_used',
                 'resistance_left', 'cover_bonus')

    def __init__(self, ability, natural, naturals, modifier, total, dc, success,
                 auto_fail, advantage, resistance_used, resistance_left,
                 cover_bonus=0):
        self.ability = ability
        self.natural = natural
        self.naturals = list(naturals or [])
        self.modifier = modifier
        self.total = total
        self.dc = dc
        self.success = bool(success)
        self.auto_fail = bool(auto_fail)
        self.advantage = advantage
        self.resistance_used = bool(resistance_used)
        self.resistance_left = resistance_left
        self.cover_bonus = int(cover_bonus or 0)


def _roll_d20(rng, advantage, disadvantage):
    """Пара (кости, режим, взятая). 20 и 1 здесь не особые случаи."""
    if advantage and disadvantage:
        return [rng.randint(1, 20)], 'cancel', None
    if advantage or disadvantage:
        first = rng.randint(1, 20)
        second = rng.randint(1, 20)
        kept = max(first, second) if advantage else min(first, second)
        mode = 'advantage' if advantage else 'disadvantage'
        return [first, second], mode, kept
    natural = rng.randint(1, 20)
    return [natural], 'normal', natural


def saving_throw(creature, ability, dc, *, rng=None, advantage=False,
                 disadvantage=False, allow_legendary=True, disabling=False,
                 damage_fail=0, damage_success=0, bonus=0):
    """d20 + бонус против Сл. Натуральные 20 и 1 не автоуспех и не автопровал.

    bonus — укрытие к спасброску Ловкости. Ноль не меняет бросок.
    """
    ability = ability_of(ability) or ability or 'dex'
    source = rng or getattr(creature, '_rng', None) or random
    disadvantage = bool(disadvantage) or save_disadvantage(creature, ability)
    auto = auto_fail_save(creature, ability)
    modifier = save_bonus(creature, ability)
    try:
        dc_value = int(dc)
    except (TypeError, ValueError):
        dc_value = 10
    cover = int(bonus or 0)
    if auto:
        roll = SaveRoll(ability, None, [], modifier, None, dc_value, False,
                        True, 'auto_fail', False, legendary_resistance_remaining(creature),
                        cover)
    else:
        dice, mode, kept = _roll_d20(source, bool(advantage), disadvantage)
        natural = dice[0] if mode == 'cancel' else kept
        total = int(natural) + int(modifier) + cover
        roll = SaveRoll(ability, natural, dice, modifier, total, dc_value,
                        total >= dc_value, False, mode, False,
                        legendary_resistance_remaining(creature), cover)
    if (not roll.success and allow_legendary
            and legendary_resistance_remaining(creature) > 0
            and worth_legendary_resistance(
                creature, disabling=disabling, damage_fail=damage_fail,
                damage_success=damage_success)):
        creature.legendary_resistance_remaining = legendary_resistance_remaining(creature) - 1
        roll.success = True
        roll.resistance_used = True
        roll.resistance_left = creature.legendary_resistance_remaining
    return roll


def _distance_ft(attacker, target, distance_ft):
    if distance_ft is not None:
        return float(distance_ft)
    from battle_strategies import distance_ft_between
    return float(distance_ft_between(attacker, target))


def attack_modifiers(attacker, target, distance_ft=None):
    """(преимущество, помеха, автокрит в 5 футах) для броска атакующего по цели.

    Любое число источников с каждой стороны схлопывается в один флаг.
    Оба флага сразу означают, что бросок обычный (RAW).
    """
    dist = _distance_ft(attacker, target, distance_ft)
    near = dist <= 5
    attacker_ids = _ids(attacker)
    target_ids = _ids(target)
    advantage = False
    disadvantage = False
    if 'invisible' in attacker_ids:
        advantage = True
    if target_ids & {'blinded', 'paralyzed', 'petrified', 'restrained', 'stunned', 'unconscious'}:
        advantage = True
    if 'prone' in target_ids and near:
        advantage = True
    if 'blinded' in attacker_ids or 'poisoned' in attacker_ids or 'prone' in attacker_ids:
        disadvantage = True
    if 'restrained' in attacker_ids:
        disadvantage = True
    if exhaustion_level(attacker) >= 3:
        disadvantage = True
    if _frightened_disadvantage(attacker, target):
        disadvantage = True
    if 'invisible' in target_ids:
        disadvantage = True
    if 'prone' in target_ids and not near:
        disadvantage = True
    force_crit = near and bool(target_ids & {'paralyzed', 'unconscious'})
    return advantage, disadvantage, force_crit


def _frightened_disadvantage(attacker, target):
    """Помеха на броски атаки, пока существо испугано.

    Линию видимости до источника симулятор не строит. Ослеплённый источник
    страха не видит, поэтому от испуга помехи нет (слепота даёт свою).
    """
    del target
    if has_condition(attacker, 'blinded'):
        return False
    return has_condition(attacker, 'frightened')


def fear_sources(creature, sides):
    found = []
    seen = set()
    for item in active_conditions(creature):
        if item.get('id') != 'frightened':
            continue
        source = _resolve_source(item, sides)
        if source is None or not getattr(source, 'alive', False):
            continue
        key = id(source)
        if key in seen:
            continue
        seen.add(key)
        found.append(source)
    return found


def charm_blocks(attacker, target):
    if target is None:
        return False
    for item in active_conditions(attacker):
        if item.get('id') != 'charmed':
            continue
        if _same_source(item, target):
            return True
    return False


def _resolve_source(cond, sides):
    uid = cond.get('source_uid')
    name = cond.get('source_name')
    for creature in iter_creatures(sides):
        if uid and getattr(creature, 'uid', None) == uid:
            return creature
    if name:
        for creature in iter_creatures(sides):
            if getattr(creature, 'name', None) == name:
                return creature
    return None


def condition_marks(creature):
    parts = []
    for item in active_conditions(creature):
        parts.append(condition_short(item.get('id'), item.get('level')))
    return ' '.join(parts)


def condition_tooltip(creature):
    lines = []
    name = getattr(creature, 'name', '') or 'существо'
    hp = getattr(creature, 'hp', '?')
    max_hp = getattr(creature, 'max_hp', '?')
    lines.append(f'{name}: {hp}/{max_hp} хитов')
    items = active_conditions(creature)
    if not items:
        lines.append('Состояний нет')
        return '\n'.join(lines)
    for item in items:
        label = condition_name(item.get('id'))
        if item.get('id') == 'exhaustion':
            label = f'{label} {item.get("level")}'
        extra = duration_text(item.get('duration'), item.get('id'))
        source = item.get('source_name')
        if source:
            extra = f'{extra}; источник {source}'
        if item.get('duration', {}).get('escape_dc'):
            extra = f'{extra}; Сл высвобождения {item["duration"]["escape_dc"]}'
        lines.append(f'{condition_short(item.get("id"), item.get("level"))} {label} — {extra}')
    speed = effective_speed(creature)
    base = getattr(creature, 'speed', None)
    if base is not None and speed != base:
        lines.append(f'Скорость сейчас {speed} фт (база {base})')
    return '\n'.join(lines)


def describe_applied(target, cond):
    label = condition_name(cond.get('id'))
    if cond.get('id') == 'exhaustion':
        label = f'{label} {cond.get("level")}'
    source = cond.get('source_name')
    how = duration_text(cond.get('duration'), cond.get('id'))
    tail = how
    if source:
        tail = f'{how}, источник {source}'
    return f'{getattr(target, "name", "Цель")}: состояние «{label}» ({tail})'


def describe_removed(target, cond, reason):
    label = condition_name(cond.get('id'))
    if cond.get('id') == 'exhaustion':
        label = f'{label} {cond.get("level")}'
    why = reason or cond.get('removed_because') or 'снято'
    return f'{getattr(target, "name", "Цель")}: состояние «{label}» снято ({why})'


def save_text(creature, roll, *, title=None):
    ability = ABILITY_RU.get(roll.ability, roll.ability or '')
    name = getattr(creature, 'name', 'Существо')
    head = f'{name}: спасбросок {ability}'
    if title:
        head = f'{name}: {title}, спасбросок {ability}'
    if roll.auto_fail:
        body = f'{head} — автоматический провал'
    else:
        dice = ''
        if roll.advantage == 'advantage' and len(roll.naturals) == 2:
            dice = f', преимущество {roll.naturals[0]}/{roll.naturals[1]}'
        elif roll.advantage == 'disadvantage' and len(roll.naturals) == 2:
            dice = f', помеха {roll.naturals[0]}/{roll.naturals[1]}'
        elif roll.advantage == 'cancel':
            dice = ', преимущество и помеха гасятся'
        mod = roll.modifier or 0
        cover = int(getattr(roll, 'cover_bonus', 0) or 0)
        cover_txt = f' укрытие {cover:+d}' if cover else ''
        body = (f'{head} {roll.total} против Сл {roll.dc} '
                f'(d20 {roll.natural} {mod:+d}{cover_txt}{dice}) — '
                f'{"успех" if roll.success and not roll.resistance_used else "провал"}')
    if roll.resistance_used:
        left = roll.resistance_left
        body = (f'{body}. Легендарное сопротивление: успех вместо провала '
                f'(осталось {left})')
    elif roll.success and not roll.auto_fail:
        pass
    return body


def turn_bounds(creature, sides, moment):
    """Снимает состояния «до начала/конца хода» этого существа. moment: start|end."""
    removed = []
    uid = getattr(creature, 'uid', None)
    why = 'начало хода' if moment == 'start' else 'конец хода'
    for other in iter_creatures(sides):
        for item in list(active_conditions(other)):
            duration = item.get('duration') or {}
            if duration.get('kind') != moment:
                continue
            whose = duration.get('whose') or 'target'
            if whose == 'target' and other is not creature:
                continue
            if whose == 'source' and (not uid or item.get('source_uid') != uid):
                continue
            removed.append((other, item))
            remove_condition(other, cond=item, reason=why)
    return removed


def tick_rounds_and_saves(creature, sides, round_no=None):
    """Конец хода цели: повторный спасбросок, затем минус раунд.

    Возвращает список (событие-словарь) для журнала: kind, text и поля броска.
    """
    notes = []
    for item in list(active_conditions(creature)):
        duration = item.get('duration') or {}
        if duration.get('kind') != 'repeat_save':
            continue
        if not getattr(creature, 'alive', False):
            break
        ability = duration.get('ability') or 'wis'
        dc = duration.get('dc') or 10
        disabling = item.get('id') in HARD_DISABLE
        roll = saving_throw(creature, ability, dc, disabling=disabling)
        success = roll.success
        notes.append(_save_note(creature, roll, item))
        if success:
            remove_condition(creature, cond=item, reason='успешный повторный спасбросок')
            notes.append({
                'kind': 'condition', 'result': 'removed', 'condition': item.get('id'),
                'text': describe_removed(creature, item, 'успешный повторный спасбросок'),
            })
    if not getattr(creature, 'alive', False):
        return notes
    for item in list(active_conditions(creature)):
        duration = item.get('duration') or {}
        kind = duration.get('kind')
        rounds = duration.get('rounds')
        if kind not in ('rounds', 'repeat_save') or rounds is None:
            continue
        if item not in active_conditions(creature):
            continue
        duration['rounds'] = int(rounds) - 1
        if duration['rounds'] <= 0:
            remove_condition(creature, cond=item, reason='истёк срок')
            notes.append({
                'kind': 'condition', 'result': 'removed', 'condition': item.get('id'),
                'text': describe_removed(creature, item, 'истёк срок'),
            })
    return notes


def _save_note(creature, roll, cond):
    return {
        'kind': 'save',
        'result': 'success' if roll.success else 'fail',
        'text': save_text(creature, roll, title=condition_name(cond.get('id'))),
        'natural': roll.natural,
        'naturals': list(roll.naturals),
        'modifier': roll.modifier,
        'total': roll.total,
        'dc': roll.dc,
        'save_ability': roll.ability,
        'advantage': roll.advantage,
        'resistance_used': roll.resistance_used,
        'condition': cond.get('id'),
        'auto_fail': roll.auto_fail,
    }


def try_stand(creature):
    """Вставание из положения лёжа стоит половину скорости. None, если нельзя."""
    if not has_condition(creature, 'prone'):
        return None
    if is_incapacitated(creature):
        return None
    speed = effective_speed(creature)
    if speed <= 0:
        return None
    cost = speed // 2
    moved = int(getattr(creature, 'moved_ft', 0) or 0)
    if moved + cost > speed:
        return None
    try:
        creature.moved_ft = moved + cost
    except (AttributeError, TypeError):
        return None
    removed = remove_condition(creature, 'prone', reason='встал')
    if not removed:
        return None
    return cost, removed[0]


def movement_blocked_by_fear(creature, origin, new_anchor, sides, anchor_of):
    """True, если шаг приближает к источнику страха. origin/new_anchor — якоря."""
    if origin is None or new_anchor is None:
        return False
    for source in fear_sources(creature, sides):
        there = anchor_of(source)
        if there is None:
            continue
        old = max(abs(origin[0] - there[0]), abs(origin[1] - there[1]))
        new = max(abs(new_anchor[0] - there[0]), abs(new_anchor[1] - there[1]))
        if new < old:
            return True
    return False


def sync_manual_conditions(creature, selected_ids, exhaustion=0):
    """Ручная правка: отмеченные состояния висят, пока их не снимут."""
    selected = set(selected_ids or [])
    for item in list(active_conditions(creature)):
        cid = item.get('id')
        if cid in ('speed_zero',):
            continue
        if cid == 'exhaustion':
            continue
        if cid not in selected:
            remove_condition(creature, cond=item, reason='снято вручную')
    have = _ids(creature)
    for cid in selected:
        if cid in have or cid == 'exhaustion':
            continue
        apply_condition(creature, cid, duration=permanent_duration(), note='вручную')
    set_exhaustion(creature, exhaustion)
