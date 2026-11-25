"""Разбор и исполнение действий со спасброском.

Конус и линия на сетке — приближение: все враги в пределах дистанции для конуса
и радиуса, для линии — те, кто почти на одной линии с ближайшим врагом.
Настоящие шаблоны области — отдельная задача.
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

_CONE_RE = re.compile(r'(\d+)\s*[-–]?\s*футов\w*\s+конус', re.IGNORECASE)
_LINE_RE = re.compile(r'(\d+)\s*[-–]?\s*футов\w*\s+лин', re.IGNORECASE)
_RADIUS_RE = re.compile(
    r'(?:радиус\w*\s+(\d+)|(\d+)\s*[-–]?\s*футов\w*\s+радиус)', re.IGNORECASE)
_WITHIN_RE = re.compile(r'в пределах\s+(\d+)\s+фут', re.IGNORECASE)
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


def _area(text):
    cone = _CONE_RE.search(text or '')
    if cone:
        return 'cone', int(cone.group(1))
    line = _LINE_RE.search(text or '')
    if line:
        return 'line', int(line.group(1))
    radius = _RADIUS_RE.search(text or '')
    if radius:
        return 'radius', int(radius.group(1) or radius.group(2))
    within = _WITHIN_RE.search(text or '')
    if within:
        return 'radius', int(within.group(1))
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
    shape, reach = _area(desc or '')
    conditions = _conditions_in(desc or '')
    if damage is None and not conditions:
        return None, (f'эффект «{name}» не разобран и остаётся текстом')
    single = bool(re.search(
        r'одно существо|одну цель|нацеливается на одно|одному существу',
        desc or '', re.IGNORECASE))
    everyone = bool(re.search(r'все существа|каждое существо|каждого существа',
                              desc or '', re.IGNORECASE))
    if shape is None:
        shape = 'single' if single or not everyone else 'radius'
        reach = reach or 30
    elif single and not everyone:
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


def _in_line(attacker, target, battle_map):
    """TODO: шаблон линии. Сейчас — та же линия клеток, допуск в 1 клетку."""
    if battle_map is None:
        return True
    origin = battle_map.get_pos(attacker)
    there = battle_map.get_pos(target)
    if not origin or not there:
        return True
    dx = abs(float(origin[0]) - float(there[0]))
    dy = abs(float(origin[1]) - float(there[1]))
    return min(dx, dy) <= 1


def targets_for(attacker, effect, sides, ignore, battle_map, focus=None):
    reach = int(effect.get('range_ft') or 5)
    shape = effect.get('area') or 'radius'
    found = []
    for creature in iter_creatures(sides):
        if not _hostile(attacker, creature, ignore):
            continue
        if _distance(attacker, creature, battle_map) > reach:
            continue
        if shape == 'line' and not _in_line(attacker, creature, battle_map):
            continue
        found.append(creature)
    if shape == 'single':
        if focus is not None and focus in found:
            return [focus]
        if not found:
            return []
        found.sort(key=lambda creature: _distance(attacker, creature, battle_map))
        return found[:1]
    return found


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


def execute_effect(attacker, effect, sides, ignore, battle_map, *,
                   round_no=None, focus=None, legendary=False, lair=False):
    """Спасбросок по целям области. Возвращает CombatEvent."""
    from combat_core import modify_damage

    events = []
    if not effect or not getattr(attacker, 'alive', False):
        return events
    targets = targets_for(attacker, effect, sides, ignore, battle_map, focus=focus)
    title = effect.get('name') or 'эффект'
    shape = effect.get('area')
    if effect.get('choice') or shape in ('cone', 'line'):
        # TODO: ручной выбор целей и настоящие шаблоны конуса/линии.
        note = ('выбор целей упрощён: враги в пределах дистанции'
                if effect.get('choice') or shape == 'cone'
                else 'линия упрощена до клеток на одной оси')
    else:
        note = None
    if not targets:
        events.append(_event(
            'save', f'{attacker.name} не находит целей для «{title}»',
            attacker, None, round_no, result='no_target', action=title,
            legendary=legendary, reason=note))
        return events
    raw = _roll_damage(attacker, effect.get('damage')) if effect.get('damage') else 0
    header = (f'{attacker.name} применяет «{title}»'
              f' ({shape or "область"} {effect.get("range_ft")} фт)')
    if lair:
        header = f'🕳 {attacker.name} — действие логова «{title}»'
    elif legendary:
        header = f'👑 {header}'
    events.append(_event(
        'save', header, attacker, None, round_no, action=title,
        legendary=legendary, reason=note, result='area'))
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
            condition=(conditions[0] if conditions else None)))
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
    if effect.get('damage'):
        reach = int(effect.get('range_ft') or 5)
        try:
            step = effective_speed(attacker)
        except (TypeError, ValueError):
            step = int(getattr(attacker, 'speed', 0) or 0)
        widened = dict(effect)
        widened['range_ft'] = reach + max(0, int(step))
        return bool(targets_for(attacker, widened, sides, ignore, battle_map, focus=focus))
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
