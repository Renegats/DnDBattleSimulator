"""Оркестратор раунда, независимый от интерфейса.

Ни диалогов, ни виджетов. Возвращает RoundResult: распаковка
`outcome, text = run_round(...)` сохранена, текст собран из CombatEvent
(`result.events`).

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


def _initiative_bonus(enemy) -> int:
    """Дополнительный бонус к броску, помимо мода Ловкости. По умолчанию 0."""
    raw = getattr(enemy, 'initiative_bonus', 0)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
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

    Бросок: d20 + мод Ловкости + дополнительный бонус (по умолчанию 0).
    Ничья: большее значение Ловкости, затем
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
            modifier = dex_modifier(enemy) + _initiative_bonus(enemy)
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


def _bound_events(pairs, round_no, reason):
    from conditions import describe_removed
    out = []
    for creature, cond in pairs:
        out.append(CombatEvent(
            kind='condition', result='removed', round=round_no,
            condition=cond.get('id'),
            actor=getattr(creature, 'name', None),
            actor_id=id(creature),
            actor_side=getattr(creature, 'side', None),
            reason=reason,
            text=describe_removed(creature, cond, reason)))
    return out


def _from_note(creature, note, round_no):
    auto = bool(note.get('auto_fail'))
    return CombatEvent(
        kind=note.get('kind') or 'save',
        result=note.get('result'),
        text=note.get('text'),
        round=round_no,
        actor=getattr(creature, 'name', None),
        actor_id=id(creature),
        actor_side=getattr(creature, 'side', None),
        natural=note.get('natural'),
        naturals=list(note.get('naturals') or []),
        modifier=note.get('modifier'),
        attack_total=note.get('total'),
        dc=note.get('dc'),
        ac=note.get('dc'),
        save_ability=note.get('save_ability'),
        advantage='auto_fail' if auto else note.get('advantage'),
        resistance_used=bool(note.get('resistance_used')),
        condition=note.get('condition'),
    )


def _open_turn(attacker, sides, round_no):
    from conditions import iter_creatures, release_grapples_from, turn_bounds
    from effects import roll_recharges
    events = _bound_events(turn_bounds(attacker, sides, 'start'), round_no, 'начало хода')
    for creature in iter_creatures(sides):
        for owner, cond in release_grapples_from(creature, sides):
            events.extend(_bound_events([(owner, cond)], round_no, 'источник не может держать'))
    events.extend(roll_recharges(attacker, round_no))
    return events


def _close_turn(attacker, sides, round_no):
    from conditions import tick_rounds_and_saves, turn_bounds
    events = [_from_note(attacker, note, round_no)
              for note in tick_rounds_and_saves(attacker, sides, round_no)]
    events.extend(_bound_events(turn_bounds(attacker, sides, 'end'), round_no, 'конец хода'))
    return events


def _fear_allow(battle_map, attacker, sides):
    from conditions import fear_sources, movement_blocked_by_fear
    if battle_map is None or not fear_sources(attacker, sides):
        return None

    def allow(hx, hy):
        origin = battle_map._anchor_h(attacker)
        return not movement_blocked_by_fear(
            attacker, origin, (hx, hy), sides, battle_map._anchor_h)

    return allow


def _opening_specials(attacker, sides, ignore, battle_map, focus, round_no):
    from effects import execute_effect, opening_effects, targets_for
    events = []
    for effect in opening_effects(attacker):
        if not targets_for(attacker, effect, sides, ignore, battle_map, focus=focus):
            continue
        events.extend(execute_effect(
            attacker, effect, sides, ignore, battle_map,
            round_no=round_no, focus=focus))
    return events


class ManualAction:
    """Решение игрока вместо мозга. kind: attack, effect, skip, auto."""

    __slots__ = ('kind', 'attack', 'effect', 'target', 'placement', 'include')

    def __init__(self, kind, attack=None, effect=None, target=None,
                 placement=None, include=None):
        self.kind = kind
        self.attack = attack
        self.effect = effect
        self.target = target
        self.placement = placement
        self.include = include


def _manual_note(attacker, text, round_no, target=None):
    return CombatEvent(
        kind='decision', round=round_no, actor=attacker.name, actor_id=id(attacker),
        actor_side=getattr(attacker, 'side', None),
        target=getattr(target, 'name', None) if target is not None else None,
        target_id=id(target) if target is not None else None,
        target_side=getattr(target, 'side', None) if target is not None else None,
        reason='ручное управление', text=text)


def _act_manual(attacker, manual, side_idx, sides, ignore_sides, battle_map,
                auto_move, crit_mode, round_no, events, effective_speed):
    """Ход по выбору игрока: одна атака, область или пропуск."""
    ignore = ignore_sides.get(side_idx, set())
    if manual.kind == 'skip':
        events.append(_manual_note(
            attacker, f'🎛 {attacker.name} пропускает ход (ручное управление)', round_no))
        return
    if manual.kind == 'effect':
        effect = manual.effect
        if not effect:
            events.append(_manual_note(
                attacker, f'🎛 {attacker.name}: нет выбранной области', round_no))
            return
        from effects import consume_recharge, execute_effect
        title = effect.get('name') or 'область'
        events.append(_manual_note(
            attacker, f'🎛 {attacker.name}: ручной выбор «{title}»', round_no))
        produced = execute_effect(
            attacker, effect, sides, ignore, battle_map, round_no=round_no,
            placement=manual.placement, include=manual.include)
        if effect.get('recharge') and any(event.result == 'area' for event in produced):
            consume_recharge(attacker, effect.get('name'))
        events.extend(produced)
        return
    target = manual.target
    attack = manual.attack
    if attack is None:
        attacks = list(getattr(attacker, 'attacks', None) or [])
        attack = attacks[0] if attacks else None
    if target is None or attack is None or not getattr(target, 'alive', False):
        events.append(_manual_note(
            attacker, f'{attacker.name} - нет подходящих целей для атаки', round_no))
        return
    events.append(_manual_note(
        attacker,
        f'🎛 {attacker.name}: ручная атака «{getattr(attack, "name", "удар")}» '
        f'по {target.name}',
        round_no, target))
    reach = int(getattr(attack, 'range_ft', 5) or 5)
    budget = effective_speed(attacker)
    allow = _fear_allow(battle_map, attacker, sides)
    if battle_map is not None and battle_map.get_pos(attacker) and battle_map.get_pos(target):
        dist = battle_map.distance_ft(attacker, target)
        if dist > reach and auto_move and budget - int(getattr(attacker, 'moved_ft', 0) or 0) >= 5:
            origin = battle_map.get_pos(attacker)
            battle_map.move_towards(attacker, target, budget, reach_ft=reach, allow=allow)
            dest = battle_map.get_pos(attacker)
            if origin and dest and (origin[0], origin[1]) != (dest[0], dest[1]):
                events.append(CombatEvent(
                    kind='move', round=round_no, actor=attacker.name,
                    actor_id=id(attacker), actor_side=getattr(attacker, 'side', None),
                    target=target.name, target_id=id(target),
                    target_side=getattr(target, 'side', None), action='движение',
                    from_pos=(origin[0], origin[1]), to_pos=(dest[0], dest[1]),
                    reason='ручное управление',
                    text=(f'{attacker.name} перемещается {format_pos(origin)} → '
                          f'{format_pos(dest)}')))
            dist = battle_map.distance_ft(attacker, target)
        if dist > reach:
            events.append(CombatEvent(
                kind='out_of_reach', round=round_no, actor=attacker.name,
                actor_id=id(attacker), actor_side=getattr(attacker, 'side', None),
                target=target.name, target_id=id(target),
                target_side=getattr(target, 'side', None),
                reason='ручное управление',
                text=(f'{attacker.name} не может достать {target.name} '
                      f'({dist} фт > {reach} фт)')))
            return
    execute_strikes(attacker, target, [attack], sides, ignore_sides, battle_map,
                    crit_mode=crit_mode, round_no=round_no, events=events)


def _act_turn(attacker, side_idx, sides, side_names, ignore_sides, battle_map,
              engine, auto_move, crit_mode, round_no, events,
              effective_speed, is_incapacitated, try_stand,
              replacing_effect, should_replace_attacks, controller=None):
    """Ход одного существа: состояния, особое действие или удары.

    side_names не используется: сигнатура совпадает с вызовом из раунда,
    чтобы не тащить лишние замыкания.
    """
    del side_names
    if is_incapacitated(attacker):
        events.append(CombatEvent(
            kind='condition', result='skip', round=round_no, condition='incapacitated',
            actor=attacker.name, actor_id=id(attacker),
            actor_side=getattr(attacker, 'side', None),
            text=f'{attacker.name} недееспособен и пропускает ход'))
        return
    stood = try_stand(attacker)
    if stood:
        cost, _cond = stood
        events.append(CombatEvent(
            kind='condition', result='removed', round=round_no, condition='prone',
            actor=attacker.name, actor_id=id(attacker),
            actor_side=getattr(attacker, 'side', None),
            text=(f'{attacker.name} встаёт, тратя {cost} фт (половина скорости). '
                  f'Состояние «сбит с ног» снято')))

    manual = controller(attacker, side_idx) if controller is not None else None
    if manual is not None and getattr(manual, 'kind', None) not in (None, 'auto'):
        _act_manual(attacker, manual, side_idx, sides, ignore_sides, battle_map,
                    auto_move, crit_mode, round_no, events, effective_speed)
        return

    ignore = ignore_sides.get(side_idx, set())
    decision = engine.decide(attacker, sides, ignore)
    target = decision.target
    breath = replacing_effect(attacker)
    plan_breath = should_replace_attacks(
        attacker, breath, sides, ignore, battle_map, target)
    if not plan_breath:
        events.extend(_opening_specials(
            attacker, sides, ignore, battle_map, target, round_no))
    if not target:
        fired = _replacing_special(
            attacker, breath if plan_breath else None, sides, ignore,
            battle_map, None, round_no)
        if fired:
            events.extend(fired)
            return
        events.append(CombatEvent(
            kind='no_target', round=round_no, actor=attacker.name,
            actor_id=id(attacker), actor_side=getattr(attacker, 'side', None),
            text=f'{attacker.name} - нет подходящих целей для атаки'))
        return
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
            return
        reach = strike_reach(strikes)
    else:                           # smart-одиночная (tier>=2)
        strikes = [decision.attack]
        reach = decision.target_dist_ft

    move_reach = reach
    if plan_breath and breath is not None:
        move_reach = max(reach, int(breath.get('range_ft') or 0))
    budget = effective_speed(attacker)
    allow = _fear_allow(battle_map, attacker, sides)
    in_reach = True
    if battle_map is not None and \
            battle_map.get_pos(attacker) and battle_map.get_pos(target):
        dist = battle_map.distance_ft(attacker, target)
        if decision.move_intent == 'hold' and dist <= move_reach:
            pass
        elif dist > move_reach and auto_move and budget - int(getattr(attacker, 'moved_ft', 0) or 0) >= 5:
            origin = battle_map.get_pos(attacker)
            battle_map.move_towards(attacker, target, budget,
                                    reach_ft=move_reach, allow=allow)
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
        if plan_breath:
            fired = _replacing_special(
                attacker, breath, sides, ignore, battle_map, target, round_no)
            if fired:
                start = len(events)
                events.extend(fired)
                _stamp_reason(events, start, decision.rationale)
                return
        if dist > reach:
            in_reach = False
            events.append(CombatEvent(
                kind='out_of_reach', round=round_no, actor=attacker.name,
                actor_id=id(attacker), actor_side=getattr(attacker, 'side', None),
                target=getattr(target, 'name', None), target_id=id(target),
                target_side=getattr(target, 'side', None),
                reason=decision.rationale or None,
                text=(f'{attacker.name} не может достать {target.name} '
                      f'({dist} фт > {reach} фт)')))
        elif decision.attack is None and decision.tier <= 1 \
                and not getattr(attacker, 'multiattack', None):
            strikes = resolve_strikes(attacker, target)
            if not strikes:
                return
    elif plan_breath:
        fired = _replacing_special(
            attacker, breath, sides, ignore, battle_map, target, round_no)
        if fired:
            start = len(events)
            events.extend(fired)
            _stamp_reason(events, start, decision.rationale)
            return
    if not in_reach:
        return

    before = len(events)
    execute_strikes(attacker, target, strikes, sides, ignore_sides, battle_map,
                    crit_mode=crit_mode, round_no=round_no, events=events)
    _stamp_reason(events, before, decision.rationale)


def _replacing_special(attacker, effect, sides, ignore, battle_map, focus, round_no):
    from effects import consume_recharge, execute_effect, targets_for
    if effect is None:
        return []
    if not targets_for(attacker, effect, sides, ignore, battle_map, focus=focus):
        return []
    events = execute_effect(
        attacker, effect, sides, ignore, battle_map, round_no=round_no, focus=focus)
    if effect.get('recharge'):
        consume_recharge(attacker, effect.get('name'))
    return events


def run_round(sides, side_names, ignore_sides, battle_map, engine, auto_move=True,
              crit_mode='double_all', rng=None, round_no=None, *, quiet=False,
              controller=None):
    """Один раунд боя. outcome: 'continue' | 'over' | 'empty'.

    Результат распаковывается в (outcome, text). События — result.events.
    text равен render_log(events). quiet=True не собирает этот текст: пакетный
    прогон считает урон по событиям и не пишет журнал.
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

    from conditions import effective_speed, is_incapacitated, try_stand
    from effects import replacing_effect, run_lair, should_replace_attacks

    for side in sides:
        for enemy in side:
            if enemy.alive and getattr(enemy, 'lair_actions', None):
                events.extend(run_lair(
                    enemy, sides, ignore_sides, battle_map, round_no))

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
        events.extend(_open_turn(attacker, sides, round_no))
        try:
            _act_turn(attacker, side_idx, sides, side_names, ignore_sides, battle_map,
                      engine, auto_move, crit_mode, round_no, events,
                      effective_speed, is_incapacitated, try_stand,
                      replacing_effect, should_replace_attacks, controller)
        finally:
            events.extend(_close_turn(attacker, sides, round_no))
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
    text = '' if quiet else render_log(events)
    return RoundResult(outcome, text, events)