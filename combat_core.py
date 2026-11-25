"""Чистый слой боевого расчёта: без tkinter и без состояния миксина.

modify_damage уважает УСЛОВНЫЕ иммунитеты: запись «дробящий от немагического
оружия» не блокирует атаку с magical=True (RAW). Семантика защиты берётся из
decision_engine — единый источник истины, чтобы мозг и исполнитель не расходились.
"""
from decision_engine import (dmg_canon, active_defenses, is_nonmagical_only)
from battle_strategies import distance_ft_between, is_healing_attack
from creature_size import space_distance_ft

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


def execute_strikes(attacker, target, strikes, sides, ignore_sides, battle_map,
                    crit_mode=DEFAULT_CRIT_MODE):
    if target is None:
        return [], False
    crit_mode = normalize_crit_mode(crit_mode)
    lines, any_killed = [], False
    ignore = ignore_sides.get(attacker.side, set())
    for atk in strikes:
        if is_healing_attack(atk):
            if (target is None or not getattr(target, 'alive', False)
                    or getattr(target, 'side', None) != getattr(attacker, 'side', None)):
                lines.append(f'{attacker.name} не применяет {atk.name}: лечить некого')
                continue
            if not in_range_of(attacker, target, atk, battle_map):
                lines.append(f'{attacker.name} не может достать {target.name} лечением '
                             f'({atk.name})')
                continue
            gained = _apply_heal(attacker, target, atk)
            lines.append(f'{attacker.name} → {target.name} ({atk.name}) - ЛЕЧЕНИЕ! '
                         f'+{gained} HP ({target.hp}/{target.max_hp})')
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
        hit, damage, attack_roll, critical, damage_info = attacker.perform_attack(
            atk, target.ac, crit_mode=crit_mode)
        if hit:
            magical = bool(getattr(atk, 'magical', False))
            damage, dmg_note = modify_damage(target, damage, atk.damage_type, magical=magical)
            target.take_damage(damage)
            extra_notes = []
            for extra in getattr(atk, 'extra_damage', None) or []:
                raw = _roll_component(attacker, extra, critical, crit_mode)
                final, note = modify_damage(target, raw, extra.get('damage_type', ''),
                                            magical=magical)
                target.take_damage(final)
                label = extra.get('damage_type') or 'доп.'
                extra_notes.append(f"+ {final} ({label}){note}")
            crit_text = " КРИТИЧЕСКИЙ УДАР!" if critical else ""
            extra_text = (' ' + ' '.join(extra_notes)) if extra_notes else ''
            lines.append(f"{attacker.name} → {target.name} ({atk.name}: "
                         f"{attack_roll} vs AC {target.ac}) - ПОПАДАНИЕ!{crit_text} "
                         f"{damage_info}{dmg_note}{extra_text}")
            if not target.alive:
                lines.append(f"☠️ {target.name} УНИЧТОЖЕН!")
                any_killed = True
        else:
            lines.append(f"{attacker.name} → {target.name} ({atk.name}: "
                         f"{attack_roll} vs AC {target.ac}) - ПРОМАХ!")
    return lines, any_killed


def refresh_legendary_pool(enemy, reset=False):
    """В начале хода существа пул полный; до первого хода — тоже, если ещё не задан."""
    block = getattr(enemy, 'legendary_actions', None)
    if not block:
        return
    if reset or getattr(enemy, 'legendary_remaining', None) is None:
        enemy.legendary_remaining = int(block.get('per_round') or 0)


def legendary_after_turn(just_acted, sides, ignore_sides, battle_map,
                         crit_mode=DEFAULT_CRIT_MODE):
    """Конец чужого хода: каждое другое легендарное существо тратит одно действие.

    В бой уходит только вариант, который сводится к уже известной атаке и
    достаёт цель. Спасброски, перемещение и действия логова здесь не считаются.
    """
    lines = []
    for side in sides:
        for enemy in side:
            if enemy is just_acted or not getattr(enemy, 'alive', False):
                continue
            lines.extend(_spend_legendary(enemy, sides, ignore_sides, battle_map, crit_mode))
    return lines


def _spend_legendary(enemy, sides, ignore_sides, battle_map, crit_mode):
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
    strike_lines, _killed = execute_strikes(
        enemy, target, [attack] * count, sides, ignore_sides, battle_map, crit_mode=crit_mode)
    enemy.legendary_remaining = remaining - cost
    header = (f"👑 {enemy.name} — легендарное действие «{option['name']}» "
              f"(стоит {cost})")
    return [header, *strike_lines]