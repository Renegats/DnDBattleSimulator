"""GUI-независимый оркестратор раунда (фаза 1 миграции на Qt).

Семантика близка к прежнему BattleLogic._run_round_inner, но БЕЗ tkinter:
ни messagebox, ни вставки в виджет. Возвращает (outcome, log_text); вывод решает
вызывающий фронтенд. Оба фронтенда зависят от этого модуля.

Ход внутри раунда — по инициативе 5e (d20 + мод Ловкости), а не сторона за стороной.
"""
import random

from combat_core import (execute_strikes, resolve_strikes, strike_reach,
                         normalize_crit_mode)


def dex_modifier(enemy) -> int:
    mods = getattr(enemy, 'ability_mods', None) or {}
    if isinstance(mods, dict) and mods.get('dex') is not None:
        try:
            return int(mods['dex'])
        except (TypeError, ValueError):
            pass
    scores = getattr(enemy, 'ability_scores', None) or {}
    raw = scores.get('dex') if isinstance(scores, dict) else None
    if raw is not None:
        try:
            return (int(raw) - 10) // 2
        except (TypeError, ValueError):
            pass
    return 0


def dex_score(enemy) -> int:
    scores = getattr(enemy, 'ability_scores', None) or {}
    raw = scores.get('dex') if isinstance(scores, dict) else None
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return 10 + 2 * dex_modifier(enemy)


def living_initiative(sides, rng=None):
    """Живые существа по убыванию инициативы.

    Бросок: d20 + мод Ловкости. Ничья: большее значение Ловкости, затем
    повторный d20. rng, если передан, бросает за всех; иначе — rng существа
    (внедряемый _rng, иначе модульный random).
    """
    rows = []
    for side_idx, side in enumerate(sides):
        for enemy in side:
            if not getattr(enemy, 'alive', False):
                continue
            source = rng
            if source is None:
                source = getattr(enemy, '_rng', None) or random
            roll = source.randint(1, 20)
            total = roll + dex_modifier(enemy)
            tie = source.randint(1, 20)
            rows.append((total, dex_score(enemy), tie, side_idx, enemy))
    rows.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return rows


def run_round(sides, side_names, ignore_sides, battle_map, engine, auto_move=True,
              crit_mode='double_all', rng=None):
    """Один раунд боя. outcome: 'continue' | 'over' | 'empty'."""
    if not sides or not any(any(e.alive for e in side) for side in sides):
        return 'empty', 'Армии не созданы или все мертвы!'

    log = ['=== НОВЫЙ РАУНД БОЯ ===']
    crit_mode = normalize_crit_mode(crit_mode)
    engine.begin_round()

    for side in sides:                      # новый раунд - движение восстановлено
        for e in side:
            e.moved_ft = 0
    if battle_map is not None:              # синхронизация pos с картой
        for side in sides:
            for e in side:
                real = battle_map.get_pos(e)
                if real is not None:
                    e.pos = real

    order = living_initiative(sides, rng)
    if order:
        shown = ', '.join(f'{enemy.name} ({total})' for total, _dex, _tie, _idx, enemy in order)
        log.append(f'Инициатива: {shown}')

    for _total, _dex, _tie, side_idx, attacker in order:
        if not attacker.alive:          # умер раньше в этом раунде — ход пропускает
            continue
        decision = engine.decide(attacker, sides, ignore_sides.get(side_idx, set()))
        target = decision.target
        if not target:
            log.append(f'{attacker.name} - нет подходящих целей для атаки')
            continue
        if decision.rationale:
            log.append(f'🧠 {attacker.name}: {decision.rationale}')

        if decision.attack is None:     # делегат (tier0/1) или мультиатака
            strikes = resolve_strikes(attacker, target)
            if not strikes:
                log.append(f'{attacker.name} - нет доступных атак')
                continue
            reach = strike_reach(strikes)
        else:                           # smart-одиночная (tier>=2)
            strikes = [decision.attack]
            reach = decision.target_dist_ft

        if battle_map is not None and \
                battle_map.get_pos(attacker) and battle_map.get_pos(target):
            dist = battle_map.distance_ft(attacker, target)
            if decision.move_intent == 'hold' and dist <= reach:
                pass                    # держим дистанцию
            elif dist > reach and auto_move:
                battle_map.move_towards(attacker, target, attacker.speed,
                                        reach_ft=reach)
                dist = battle_map.distance_ft(attacker, target)
            if dist > reach:
                log.append(f'{attacker.name} не может достать {target.name} '
                           f'({dist} фт > {reach} фт)')
                continue
            if decision.attack is None and decision.tier <= 1 \
                    and not getattr(attacker, 'multiattack', None):
                strikes = resolve_strikes(attacker, target)
                if not strikes:
                    continue

        lines, _killed = execute_strikes(attacker, target, strikes,
                                         sides, ignore_sides, battle_map,
                                         crit_mode=crit_mode)
        log.extend(lines)
    log.append('')

    for side in sides:                      # фаза регенерации
        for e in side:
            if e.alive and e.regen > 0:
                prev = e.hp
                e.regenerate()
                if e.hp > prev:
                    log.append(f'💚 {e.name} восстанавливает {e.hp - prev} HP '
                               f'благодаря регенерации')

    alive = [side_names[i] for i, s in enumerate(sides) if any(e.alive for e in s)]
    if len(alive) <= 1:
        if alive:
            log.append(f'\n🎉 {alive[0]} ПОБЕДИЛА!\n')
        else:
            log.append('\n⚔️ Все стороны уничтожены! Ничья.\n')
        return 'over', '\n'.join(log)
    log.append(f"\nБитва продолжается: {' vs '.join(alive)}\n")
    return 'continue', '\n'.join(log)