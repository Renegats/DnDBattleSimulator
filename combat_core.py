"""Чистый слой боевого расчёта: без tkinter и без состояния миксина.

modify_damage уважает УСЛОВНЫЕ иммунитеты: запись «дробящий от немагического
оружия» не блокирует атаку с magical=True (RAW). Семантика защиты берётся из
decision_engine — единый источник истины, чтобы мозг и исполнитель не расходились.
"""
from decision_engine import (dmg_canon, active_defenses, is_nonmagical_only)
from battle_strategies import distance_ft_between
from creature_size import space_distance_ft


def resolve_strikes(attacker, target):
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


def execute_strikes(attacker, target, strikes, sides, ignore_sides, battle_map):
    if target is None:
        return [], False
    lines, any_killed = [], False
    ignore = ignore_sides.get(attacker.side, set())
    for atk in strikes:
        if target is None or not target.alive:
            target = nearest_in_range(attacker, atk, ignore, sides, battle_map)
            if target is None:
                break
        if not in_range_of(attacker, target, atk, battle_map):
            alt = nearest_in_range(attacker, atk, ignore, sides, battle_map)
            if alt is None:
                continue
            target = alt
        hit, damage, attack_roll, critical, damage_info = attacker.perform_attack(atk, target.ac)
        if hit:
            damage, dmg_note = modify_damage(target, damage, atk.damage_type,
                                             magical=bool(getattr(atk, 'magical', False)))
            target.take_damage(damage)
            crit_text = " КРИТИЧЕСКИЙ УДАР!" if critical else ""
            lines.append(f"{attacker.name} → {target.name} ({atk.name}: "
                         f"{attack_roll} vs AC {target.ac}) - ПОПАДАНИЕ!{crit_text} "
                         f"{damage_info}{dmg_note}")
            if not target.alive:
                lines.append(f"☠️ {target.name} УНИЧТОЖЕН!")
                any_killed = True
        else:
            lines.append(f"{attacker.name} → {target.name} ({atk.name}: "
                         f"{attack_roll} vs AC {target.ac}) - ПРОМАХ!")
    return lines, any_killed