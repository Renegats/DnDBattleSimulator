"""Чистый слой боевого расчёта: без tkinter и без состояния миксина.

modify_damage уважает УСЛОВНЫЕ иммунитеты: запись «дробящий от немагического
оружия» не блокирует атаку с magical=True (RAW). Семантика защиты берётся из
decision_engine — единый источник истины, чтобы мозг и исполнитель не расходились.
"""
from decision_engine import (dmg_canon, active_defenses, is_nonmagical_only)
from battle_strategies import distance_ft_between, is_healing_attack
from creature_size import space_distance_ft
from combat_log import CombatEvent, DamagePart

# Как стол удваивает крит. 'double_all' — историческое поведение и дефолт.
CRIT_DOUBLE_ALL = 'double_all'
CRIT_DICE_ONLY = 'dice_only'
DEFAULT_CRIT_MODE = CRIT_DOUBLE_ALL
CRIT_MODE_LABELS = {
    CRIT_DOUBLE_ALL: 'Удваивать весь урон',
    CRIT_DICE_ONLY: 'Удваивать только кости',
}


def normalize_crit_mode(value):
    """Ключ режима крита. Нет ключа, пусто или неизвестное значение → дефолт."""
    if value in CRIT_MODE_LABELS:
        return value
    for key, label in CRIT_MODE_LABELS.items():
        if value == label:
            return key
    return DEFAULT_CRIT_MODE


def resolve_strikes(attacker, target):
    if target is not None and getattr(target, 'side', None) == getattr(attacker, 'side', None):
        attack = attacker.strategy.select_attack(attacker, target)
        return [attack] if attack else []
    if getattr(attacker, 'multiattack', None):
        by_name = {a.name: a for a in attacker.attacks}
        strikes = []
        for s in attacker.multiattack:
            atk = by_name.get(s['attack'])
            if atk is None:
                continue
            strikes.extend([atk] * max(1, int(s.get('count', 1))))
        if strikes:
            return strikes
    a = attacker.strategy.select_attack(attacker, target)
    return [a] if a else []


def strike_reach(strikes):
    if not strikes:
        return 5
    return min(getattr(a, 'range_ft', 5) for a in strikes)


def in_range_of(attacker, target, atk, battle_map):
    need = getattr(atk, 'range_ft', 5)
    if battle_map is not None and battle_map.get_pos(attacker) \
            and battle_map.get_pos(target):
        return battle_map.distance_ft(attacker, target) <= need
    return space_distance_ft(attacker, target) <= need


def nearest_in_range(attacker, atk, ignore, sides, battle_map):
    need = getattr(atk, 'range_ft', 5)
    has_map = battle_map is not None and battle_map.get_pos(attacker) is not None
    best, best_d = None, None
    for side_idx, side_enemies in enumerate(sides):
        if side_idx == attacker.side:
            continue
        if side_idx in ignore or side_idx in attacker.ignore_sides:
            continue
        for e in side_enemies:
            if not e.alive:
                continue
            if not has_map:
                return e
            if battle_map.get_pos(e) is None:
                continue
            d = battle_map.distance_ft(attacker, e)
            if d <= need and (best_d is None or d < best_d):
                best, best_d = e, d
    return best


def _roll_component(attacker, comp, critical, crit_mode):
    """Дополнительный урон тем же режимом крита, что и основной бросок."""
    import random
    rng = getattr(attacker, '_rng', None) or random
    sides = int(str(comp.get('dice_type') or 'd6').split('d')[-1] or 6)
    count = int(comp.get('dice_count') or 0)
    modifier = int(comp.get('modifier') or 0)
    rolls = max(0, count)
    if critical and crit_mode == 'dice_only':
        rolls *= 2
    total = sum(rng.randint(1, max(1, sides)) for _ in range(rolls)) + modifier
    if critical and crit_mode != 'dice_only':
        total *= 2
    return max(0, total)


def modify_damage(target, raw, damage_type, magical=False):
    """Чистая функция: считает итоговый урон, НЕ наносит его.
    magical=True снимает условные иммунитеты/сопротивления «от немагического»."""
    canon = dmg_canon(damage_type)
    if not canon or raw <= 0:
        return raw, ''
    raw_imm = list(getattr(target, 'immunities', []) or [])
    imm = active_defenses(raw_imm, magical)
    vul = {dmg_canon(x) for x in (getattr(target, 'vulnerabilities', []) or [])}
    res = active_defenses(getattr(target, 'resistances', []) or [], magical)

    if canon in imm:
        return 0, f" → 0 (иммунитет: {damage_type})"
    if canon in vul:
        final = raw * 2
        return final, f" → {final} (уязвимость: {damage_type})"
    if canon in res:
        final = raw // 2
        return final, f" → {final} (сопротивление: {damage_type})"
    if magical and any(is_nonmagical_only(x) and dmg_canon(x) == canon for x in raw_imm):
        return raw, " ✦ магическое оружие пробило иммунитет к немагическому"
    return raw, ''


def _apply_heal(attacker, target, atk):
    if hasattr(attacker, 'perform_heal'):
        amount = attacker.perform_heal(atk)
    else:
        amount = 0
    if hasattr(target, 'heal'):
        return target.heal(amount)
    if not getattr(target, 'alive', False):
        return 0
    before = target.hp
    cap = getattr(target, 'max_hp', before)
    target.hp = min(cap, before + max(0, int(amount)))
    return target.hp - before


def _roll_details(roll, attack):
    """5 значений контракта perform_attack и, если есть, натуральная кость."""
    hit, damage, total, critical, info = roll
    natural = getattr(roll, 'natural', None)
    modifier = getattr(roll, 'modifier', None)
    if modifier is None:
        modifier = getattr(attack, 'attack_bonus', None)
    return hit, damage, total, critical, info, natural, modifier


def _strike_result(hit, critical, natural):
    if critical:
        return 'crit'
    if natural == 1:
        return 'nat1'
    if hit:
        return 'hit'
    return 'miss'


def _actor_fields(attacker, target, battle_map):
    def pos_of(creature):
        if creature is None:
            return None
        pos = None
        if battle_map is not None and hasattr(battle_map, 'get_pos'):
            pos = battle_map.get_pos(creature)
        if not pos:
            pos = getattr(creature, 'pos', None)
        if not pos:
            return None
        return (pos[0], pos[1])

    return {
        'actor': getattr(attacker, 'name', None),
        'actor_id': id(attacker) if attacker is not None else None,
        'actor_side': getattr(attacker, 'side', None),
        'target': getattr(target, 'name', None) if target is not None else None,
        'target_id': id(target) if target is not None else None,
        'target_side': getattr(target, 'side', None) if target is not None else None,
        'actor_pos': pos_of(attacker),
        'target_pos': pos_of(target),
    }


def execute_strikes(attacker, target, strikes, sides, ignore_sides, battle_map,
                    crit_mode=DEFAULT_CRIT_MODE, *, round_no=None, events=None,
                    legendary=False):
    """Удары и лечение. Возврат — прежний (строки, было_ли_убийство).

    Если передан events, туда дописываются CombatEvent. Строки собраны из
    event.text, поэтому текст лога не расходится со структурой.
    """
    if target is None:
        return [], False
    crit_mode = normalize_crit_mode(crit_mode)
    produced, any_killed = [], False
    ignore = ignore_sides.get(getattr(attacker, 'side', None), set())
    for atk in strikes:
        if is_healing_attack(atk):
            produced.extend(_heal_strike(
                attacker, target, atk, battle_map, round_no, legendary))
            continue
        if target is None or not target.alive:
            target = nearest_in_range(attacker, atk, ignore, sides, battle_map)
            if target is None:
                break
        if not in_range_of(attacker, target, atk, battle_map):
            alt = nearest_in_range(attacker, atk, ignore, sides, battle_map)
            if alt is None:
                continue
            target = alt
        hit_events, killed = _attack_strike(
            attacker, target, atk, battle_map, crit_mode, round_no, legendary)
        produced.extend(hit_events)
        any_killed = any_killed or killed
    if events is not None:
        events.extend(produced)
    lines = [event.text for event in produced if event.text is not None]
    return lines, any_killed


def _heal_strike(attacker, target, atk, battle_map, round_no, legendary):
    common = _actor_fields(attacker, target, battle_map)
    common.update(round=round_no, legendary=legendary, action=getattr(atk, 'name', None))
    if (target is None or not getattr(target, 'alive', False)
            or getattr(target, 'side', None) != getattr(attacker, 'side', None)):
        text = f'{attacker.name} не применяет {atk.name}: лечить некого'
        return [CombatEvent(kind='heal', result='no_target', text=text, **common)]
    if not in_range_of(attacker, target, atk, battle_map):
        text = (f'{attacker.name} не может достать {target.name} лечением '
                f'({atk.name})')
        return [CombatEvent(kind='heal', result='out_of_reach', text=text, **common)]
    before = getattr(target, 'hp', None)
    gained = _apply_heal(attacker, target, atk)
    after = getattr(target, 'hp', None)
    text = (f'{attacker.name} → {target.name} ({atk.name}) - ЛЕЧЕНИЕ! '
            f'+{gained} HP ({target.hp}/{target.max_hp})')
    return [CombatEvent(
        kind='heal', result='heal', text=text, heal_amount=gained,
        hp_before=before, hp_after=after,
        max_hp=getattr(target, 'max_hp', None), **common)]


def _attack_strike(attacker, target, atk, battle_map, crit_mode, round_no, legendary):
    roll = attacker.perform_attack(atk, target.ac, crit_mode=crit_mode)
    hit, damage, attack_roll, critical, damage_info, natural, modifier = _roll_details(roll, atk)
    result = _strike_result(hit, critical, natural)
    common = _actor_fields(attacker, target, battle_map)
    before = getattr(target, 'hp', None)
    if hit:
        magical = bool(getattr(atk, 'magical', False))
        final, dmg_note = modify_damage(target, damage, atk.damage_type, magical=magical)
        target.take_damage(final)
        parts = [DamagePart(getattr(atk, 'damage_type', '') or '', damage, final, dmg_note, False)]
        extra_notes = []
        for extra in getattr(atk, 'extra_damage', None) or []:
            raw = _roll_component(attacker, extra, critical, crit_mode)
            extra_final, note = modify_damage(target, raw, extra.get('damage_type', ''),
                                              magical=magical)
            target.take_damage(extra_final)
            label = extra.get('damage_type') or 'доп.'
            extra_notes.append(f"+ {extra_final} ({label}){note}")
            parts.append(DamagePart(label, raw, extra_final, note, True))
        crit_text = " КРИТИЧЕСКИЙ УДАР!" if critical else ""
        extra_text = (' ' + ' '.join(extra_notes)) if extra_notes else ''
        text = (f"{attacker.name} → {target.name} ({atk.name}: "
                f"{attack_roll} vs AC {target.ac}) - ПОПАДАНИЕ!{crit_text} "
                f"{damage_info}{dmg_note}{extra_text}")
        after = getattr(target, 'hp', None)
        event = CombatEvent(
            kind='attack', result=result, crit=bool(critical), text=text,
            action=getattr(atk, 'name', None), natural=natural, modifier=modifier,
            attack_total=attack_roll, ac=getattr(target, 'ac', None),
            damages=parts, hp_before=before, hp_after=after,
            max_hp=getattr(target, 'max_hp', None),
            round=round_no, legendary=legendary, **common)
        produced = [event]
        killed = not getattr(target, 'alive', True)
        if killed:
            produced.append(CombatEvent(
                kind='death', result='death', text=f"☠️ {target.name} УНИЧТОЖЕН!",
                action=getattr(atk, 'name', None), hp_before=before, hp_after=after,
                max_hp=getattr(target, 'max_hp', None),
                round=round_no, legendary=legendary, **common))
        return produced, killed
    text = (f"{attacker.name} → {target.name} ({atk.name}: "
            f"{attack_roll} vs AC {target.ac}) - ПРОМАХ!")
    event = CombatEvent(
        kind='attack', result=result, crit=False, text=text,
        action=getattr(atk, 'name', None), natural=natural, modifier=modifier,
        attack_total=attack_roll, ac=getattr(target, 'ac', None),
        damages=[], hp_before=before, hp_after=before,
        max_hp=getattr(target, 'max_hp', None),
        round=round_no, legendary=legendary, **common)
    return [event], False


def refresh_legendary_pool(enemy, reset=False):
    """В начале хода существа пул полный; до первого хода — тоже, если ещё не задан."""
    block = getattr(enemy, 'legendary_actions', None)
    if not block:
        return
    if reset or getattr(enemy, 'legendary_remaining', None) is None:
        enemy.legendary_remaining = int(block.get('per_round') or 0)


def legendary_after_turn(just_acted, sides, ignore_sides, battle_map,
                         crit_mode=DEFAULT_CRIT_MODE, *, round_no=None, events=None):
    """Конец чужого хода: каждое другое легендарное существо тратит одно действие.

    В бой уходит только вариант, который сводится к уже известной атаке и
    достаёт цель. Спасброски, перемещение и действия логова здесь не считаются.
    Возврат — список прежних текстовых строк. events, если передан, получает
    те же CombatEvent.
    """
    produced = []
    for side in sides:
        for enemy in side:
            if enemy is just_acted or not getattr(enemy, 'alive', False):
                continue
            produced.extend(_spend_legendary(
                enemy, sides, ignore_sides, battle_map, crit_mode, round_no=round_no))
    if events is not None:
        events.extend(produced)
    return [event.text for event in produced if event.text is not None]


def _spend_legendary(enemy, sides, ignore_sides, battle_map, crit_mode, round_no=None):
    from battle_strategies import damage_score
    block = getattr(enemy, 'legendary_actions', None)
    if not block:
        return []
    refresh_legendary_pool(enemy, reset=False)
    remaining = int(getattr(enemy, 'legendary_remaining', 0) or 0)
    if remaining <= 0:
        return []
    ignore = ignore_sides.get(getattr(enemy, 'side', None), set())
    by_name = {attack.name: attack for attack in getattr(enemy, 'attacks', []) or []}
    best = None
    for option in block.get('options') or []:
        if not option.get('usable') or not option.get('attack'):
            continue
        cost = int(option.get('cost') or 1)
        if cost > remaining:
            continue
        attack = by_name.get(option['attack'])
        if attack is None:
            continue
        target = nearest_in_range(enemy, attack, ignore, sides, battle_map)
        if target is None:
            continue
        score = damage_score(attack) * max(1, int(option.get('count') or 1))
        if best is None or score > best[0]:
            best = (score, option, attack, target, cost)
    if best is None:
        return []
    _score, option, attack, target, cost = best
    count = max(1, int(option.get('count') or 1))
    strikes = []
    execute_strikes(
        enemy, target, [attack] * count, sides, ignore_sides, battle_map,
        crit_mode=crit_mode, round_no=round_no, events=strikes, legendary=True)
    enemy.legendary_remaining = remaining - cost
    for event in strikes:
        if not event.reason:
            event.reason = option['name']
    header_text = (f"👑 {enemy.name} — легендарное действие «{option['name']}» "
                   f"(стоит {cost})")
    header = CombatEvent(
        kind='legendary', round=round_no, legendary=True, cost=cost,
        action=option['name'], text=header_text, reason=option.get('desc') or None,
        actor=getattr(enemy, 'name', None), actor_id=id(enemy),
        actor_side=getattr(enemy, 'side', None),
        target=getattr(target, 'name', None), target_id=id(target),
        target_side=getattr(target, 'side', None),
    )
    return [header, *strikes]