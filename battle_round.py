"""GUI-независимый оркестратор раунда (фаза 1 миграции на Qt).

Семантика 1:1 с BattleLogic._run_round_inner, но БЕЗ tkinter: ни messagebox,
ни вставки в виджет. Возвращает (outcome, log_text); вывод решает вызывающий
фронтенд. Позже BattleLogic сможет делегировать сюда же, и оркестрация станет
единственной (DIP: оба фронтенда зависят от одного чистого модуля).
"""
from combat_core import execute_strikes, resolve_strikes, strike_reach


def run_round(sides, side_names, ignore_sides, battle_map, engine, auto_move=True):
    """Один раунд боя. outcome: 'continue' | 'over' | 'empty'."""
    if not sides or not any(any(e.alive for e in side) for side in sides):
        return 'empty', 'Армии не созданы или все мертвы!'

    log = ['=== НОВЫЙ РАУНД БОЯ ===']
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

    for side_idx, side in enumerate(sides):
        for attacker in [e for e in side if e.alive]:
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
                                             sides, ignore_sides, battle_map)
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