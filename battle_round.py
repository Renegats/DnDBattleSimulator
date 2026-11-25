"""GUI-независимый оркестратор раунда (фаза 1 миграции на Qt).

Семантика близка к прежнему BattleLogic._run_round_inner, но БЕЗ tkinter:
ни messagebox, ни вставки в виджет. Возвращает RoundResult: распаковка
`outcome, text = run_round(...)` сохранена, текст собран из CombatEvent
(`result.events`). Оба фронтенда зависят от этого модуля.

Ход внутри раунда — по инициативе 5e (d20 + мод Ловкости), а не сторона за стороной.
"""
import random

from combat_core import (execute_strikes, resolve_strikes, strike_reach,
                         normalize_crit_mode, refresh_legendary_pool,
                         legendary_after_turn)
from combat_log import (CombatEvent, InitiativeEntry, InitiativeRoll,
                        RoundResult, format_pos, render_log)


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
            natural = source.randint(1, 20)
            modifier = dex_modifier(enemy)
            total = natural + modifier
            tie = source.randint(1, 20)
            rows.append(InitiativeEntry(
                total, dex_score(enemy), tie, side_idx, enemy, natural, modifier))
    rows.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return rows


def _stamp_reason(events, start, reason):
    if not reason:
        return
    for event in events[start:]:
        if not event.reason:
            event.reason = reason


def run_round(sides, side_names, ignore_sides, battle_map, engine, auto_move=True,
              crit_mode='double_all', rng=None, round_no=None):
    """Один раунд боя. outcome: 'continue' | 'over' | 'empty'.

    Результат распаковывается в (outcome, text). События — result.events.
    text всегда равен render_log(events).
    """
    if not sides or not any(any(e.alive for e in side) for side in sides):
        return RoundResult('empty', 'Армии не созданы или все мертвы!', [])

    events = [CombatEvent(kind='round_start', round=round_no,
                          text='=== НОВЫЙ РАУНД БОЯ ===')]
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
        rolls = [InitiativeRoll(
            name=row.enemy.name, side=getattr(row.enemy, 'side', row.side_idx),
            actor_id=id(row.enemy), natural=row.natural, modifier=row.modifier,
            total=row.total, tie_roll=row.tie, dex=row.dex,
        ) for row in order]
        events.append(CombatEvent(
            kind='initiative', round=round_no, text=f'Инициатива: {shown}', rolls=rolls))

    for side in sides:
        for enemy in side:
            refresh_legendary_pool(enemy, reset=False)

    previous = None
    for _total, _dex, _tie, side_idx, attacker in order:
        if previous is not None:
            legendary_after_turn(
                previous, sides, ignore_sides, battle_map, crit_mode,
                round_no=round_no, events=events)
        if not attacker.alive:          # умер раньше в этом раунде — ход пропускает
            previous = None
            continue
        refresh_legendary_pool(attacker, reset=True)  # пул возвращается в начале своего хода
        previous = attacker
        decision = engine.decide(attacker, sides, ignore_sides.get(side_idx, set()))
        target = decision.target
        if not target:
            events.append(CombatEvent(
                kind='no_target', round=round_no, actor=attacker.name,
                actor_id=id(attacker), actor_side=getattr(attacker, 'side', None),
                text=f'{attacker.name} - нет подходящих целей для атаки'))
            continue
        if decision.rationale:
            events.append(CombatEvent(
                kind='decision', round=round_no, actor=attacker.name,
                actor_id=id(attacker), actor_side=getattr(attacker, 'side', None),
                target=getattr(target, 'name', None), target_id=id(target),
                target_side=getattr(target, 'side', None),
                reason=decision.rationale,
                action=getattr(decision.attack, 'name', None),
                text=f'🧠 {attacker.name}: {decision.rationale}'))

        if decision.attack is None:     # делегат (tier0/1) или мультиатака
            strikes = resolve_strikes(attacker, target)
            if not strikes:
                events.append(CombatEvent(
                    kind='no_attack', round=round_no, actor=attacker.name,
                    actor_id=id(attacker), actor_side=getattr(attacker, 'side', None),
                    target=getattr(target, 'name', None), target_id=id(target),
                    target_side=getattr(target, 'side', None),
                    text=f'{attacker.name} - нет доступных атак'))
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
                origin = battle_map.get_pos(attacker)
                battle_map.move_towards(attacker, target, attacker.speed,
                                        reach_ft=reach)
                dest = battle_map.get_pos(attacker)
                if origin and dest and (origin[0], origin[1]) != (dest[0], dest[1]):
                    events.append(CombatEvent(
                        kind='move', round=round_no, actor=attacker.name,
                        actor_id=id(attacker), actor_side=getattr(attacker, 'side', None),
                        target=getattr(target, 'name', None), target_id=id(target),
                        target_side=getattr(target, 'side', None),
                        action='движение',
                        from_pos=(origin[0], origin[1]), to_pos=(dest[0], dest[1]),
                        reason=decision.rationale or None,
                        text=(f'{attacker.name} перемещается {format_pos(origin)} → '
                              f'{format_pos(dest)}')))
                dist = battle_map.distance_ft(attacker, target)
            if dist > reach:
                events.append(CombatEvent(
                    kind='out_of_reach', round=round_no, actor=attacker.name,
                    actor_id=id(attacker), actor_side=getattr(attacker, 'side', None),
                    target=getattr(target, 'name', None), target_id=id(target),
                    target_side=getattr(target, 'side', None),
                    reason=decision.rationale or None,
                    text=(f'{attacker.name} не может достать {target.name} '
                          f'({dist} фт > {reach} фт)')))
                continue
            if decision.attack is None and decision.tier <= 1 \
                    and not getattr(attacker, 'multiattack', None):
                strikes = resolve_strikes(attacker, target)
                if not strikes:
                    continue

        before = len(events)
        execute_strikes(attacker, target, strikes, sides, ignore_sides, battle_map,
                        crit_mode=crit_mode, round_no=round_no, events=events)
        _stamp_reason(events, before, decision.rationale)
    if previous is not None:
        legendary_after_turn(
            previous, sides, ignore_sides, battle_map, crit_mode,
            round_no=round_no, events=events)
    events.append(CombatEvent(kind='spacer', round=round_no, text=''))

    for side in sides:                      # фаза регенерации
        for e in side:
            if e.alive and e.regen > 0:
                prev = e.hp
                e.regenerate()
                if e.hp > prev:
                    gained = e.hp - prev
                    events.append(CombatEvent(
                        kind='heal', result='heal', round=round_no, action='регенерация',
                        actor=e.name, actor_id=id(e), actor_side=getattr(e, 'side', None),
                        heal_amount=gained, hp_before=prev, hp_after=e.hp,
                        max_hp=getattr(e, 'max_hp', None),
                        text=(f'💚 {e.name} восстанавливает {gained} HP '
                              f'благодаря регенерации')))

    alive = [side_names[i] for i, s in enumerate(sides) if any(e.alive for e in s)]
    if len(alive) <= 1:
        if alive:
            events.append(CombatEvent(
                kind='round_end', result='victory', round=round_no,
                text=f'\n🎉 {alive[0]} ПОБЕДИЛА!\n'))
            outcome = 'over'
        else:
            events.append(CombatEvent(
                kind='round_end', result='draw', round=round_no,
                text='\n⚔️ Все стороны уничтожены! Ничья.\n'))
            outcome = 'over'
    else:
        events.append(CombatEvent(
            kind='round_end', result='continue', round=round_no,
            text=f"\nБитва продолжается: {' vs '.join(alive)}\n"))
        outcome = 'continue'
    text = render_log(events)
    return RoundResult(outcome, text, events)