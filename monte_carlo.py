"""Пакетная симуляция боя: много независимых прогонов одной сцены.

Каждый бой начинается с глубокой копии стартового снимка (хиты, состояния,
перезарядка, легендарные действия и сопротивление, карта). Сид боя зависит
только от базового сида и номера, поэтому серия воспроизводится и в нескольких
процессах. Журнал не собирается: раунд идёт с quiet=True.

Запуск без интерфейса: python -m monte_carlo -o бой.csv
"""
import argparse
import copy
import csv
import json
import math
import multiprocessing
import os
import random
import signal
import statistics
import sys
import threading
from dataclasses import dataclass, field

from battle_history import capture_battle
from battle_map_model import BattleMap
from battle_round import run_round
from battle_strategies import (AggressiveStrategy, DefensiveStrategy,
                               RandomStrategy, SupportStrategy)
from combat_core import normalize_crit_mode
from decision_engine import DecisionEngine
from entities import Enemy
from factory import EnemyFactory
from rng_channel import bound

_STRATS = {
    'случайная': RandomStrategy,
    'агрессивная': AggressiveStrategy,
    'защитная': DefensiveStrategy,
    'поддержка': SupportStrategy,
}

_OUTCOME_RU = {
    'victory': 'победа',
    'draw': 'ничья',
    'timeout': 'таймаут',
}

_WORKER = None


class _Scene:
    """То, что capture_battle читает у окна. Без Qt."""

    def __init__(self):
        self.sides = []
        self.side_names = []
        self.ignore_sides = {}
        self.battle_map = None
        self.engine = DecisionEngine()
        self.round_no = 0
        self.battle_events = []
        self.alliance_settings = []
        self.selected = None
        self.setup = []


@dataclass
class CreatureEnd:
    uid: str
    name: str
    side_index: int
    side_name: str
    hp: int
    alive: bool
    dealt: int
    taken: int
    resistance_remaining: int | None
    recharge_ready: dict = field(default_factory=dict)


@dataclass
class BattleRow:
    number: int
    seed: int
    winner: str
    winner_index: int
    rounds: int
    outcome: str
    creatures: list


@dataclass
class RateStat:
    name: str
    count: int
    rate: float
    ci_low: float
    ci_high: float


@dataclass
class CreatureStat:
    uid: str
    name: str
    side_name: str
    side_index: int
    survival: float
    mean_hp: float
    mean_hp_alive: float | None
    mean_dealt: float
    mean_taken: float


@dataclass
class BatchReport:
    battles_requested: int
    battles_done: int
    seed: int
    max_rounds: int
    workers: int
    cancelled: bool
    sides: list
    draw: RateStat
    timeout: RateStat
    mean_rounds: float
    median_rounds: float
    round_histogram: list
    creatures: list
    battles: list


def derive_seed(base_seed, index):
    """Независимый сид боя. Хватает 31 бита, чтобы Excel не округлял номер.

    Строка, а не кортеж: в 3.12 Random принимает только int/float/str/bytes.
    """
    mixer = random.Random(f'{int(base_seed)}:{int(index)}')
    return mixer.randrange(1, 2 ** 31 - 1)


def wilson(successes, total, z=1.96):
    """95% интервал Уилсона для доли. При нуле боёв — (0, 0)."""
    successes = int(successes)
    total = int(total)
    if total <= 0:
        return 0.0, 0.0
    successes = min(total, max(0, successes))
    if successes == 0:
        low_bound = 0.0
    else:
        low_bound = None
    if successes == total:
        high_bound = 1.0
    else:
        high_bound = None
    proportion = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    centre = (proportion + z2 / (2.0 * total)) / denom
    margin = z * math.sqrt((proportion * (1.0 - proportion) + z2 / (4.0 * total)) / total) / denom
    low = 0.0 if low_bound is not None else max(0.0, centre - margin)
    high = 1.0 if high_bound is not None else min(1.0, centre + margin)
    return low, high


def creature_uid(data, side_index, index):
    if isinstance(data, dict) and data.get('uid'):
        return str(data['uid'])
    return f'{side_index}:{index}'


def side_names_of(snapshot):
    names = [str(name) for name in (snapshot.get('side_names') or [])]
    count = len(snapshot.get('sides') or [])
    while len(names) < count:
        names.append(f'Сторона {len(names) + 1}')
    return names[:count] if count else names


def roster_of(snapshot):
    names = side_names_of(snapshot)
    roster = []
    for side_index, row in enumerate(snapshot.get('sides') or []):
        side_name = names[side_index]
        for index, data in enumerate(row or []):
            data = data or {}
            roster.append({
                'uid': creature_uid(data, side_index, index),
                'name': str(data.get('name') or f'{side_name}_{index + 1}'),
                'side_index': side_index,
                'side_name': side_name,
            })
    return roster


def _is_cancel(cancel):
    if cancel is None:
        return False
    is_set = getattr(cancel, 'is_set', None)
    if callable(is_set):
        return bool(is_set())
    if callable(cancel):
        return bool(cancel())
    return bool(cancel)


def _rate(name, count, total):
    low, high = wilson(count, total)
    rate = (count / total) if total else 0.0
    return RateStat(name, int(count), rate, low, high)


def aggregate(rows, roster, *, requested, seed, max_rounds, workers, cancelled,
              side_names):
    """Сводка по уже посчитанным боям. rows можно передать в любом порядке."""
    ordered = sorted(rows, key=lambda row: row.number)
    done = len(ordered)
    names = list(side_names)
    wins = [0] * len(names)
    draws = 0
    timeouts = 0
    for row in ordered:
        if row.outcome == 'victory' and 0 <= row.winner_index < len(wins):
            wins[row.winner_index] += 1
        elif row.outcome == 'timeout':
            timeouts += 1
        else:
            draws += 1
    rounds = [row.rounds for row in ordered]
    counts = {}
    for value in rounds:
        counts[value] = counts.get(value, 0) + 1
    if counts:
        histogram = [(number, counts.get(number, 0))
                     for number in range(min(counts), max(counts) + 1)]
    else:
        histogram = []
    by_uid = {}
    for row in ordered:
        for creature in row.creatures:
            by_uid.setdefault(creature.uid, []).append(creature)
    creatures = []
    for item in roster:
        sample = by_uid.get(item['uid'], [])
        if not sample or done == 0:
            creatures.append(CreatureStat(
                item['uid'], item['name'], item['side_name'], item['side_index'],
                0.0, 0.0, None, 0.0, 0.0))
            continue
        alive = [creature for creature in sample if creature.alive]
        mean_alive = (statistics.fmean(creature.hp for creature in alive)
                      if alive else None)
        creatures.append(CreatureStat(
            item['uid'], item['name'], item['side_name'], item['side_index'],
            len(alive) / done,
            statistics.fmean(creature.hp for creature in sample),
            None if mean_alive is None else float(mean_alive),
            statistics.fmean(creature.dealt for creature in sample),
            statistics.fmean(creature.taken for creature in sample),
        ))
    return BatchReport(
        battles_requested=int(requested),
        battles_done=done,
        seed=int(seed),
        max_rounds=int(max_rounds),
        workers=int(workers),
        cancelled=bool(cancelled),
        sides=[_rate(name, wins[index], done) for index, name in enumerate(names)],
        draw=_rate('ничья', draws, done),
        timeout=_rate('таймаут', timeouts, done),
        mean_rounds=float(statistics.fmean(rounds)) if rounds else 0.0,
        median_rounds=float(statistics.median(rounds)) if rounds else 0.0,
        round_histogram=histogram,
        creatures=creatures,
        battles=ordered,
    )


def _progress_payload(rows, total, side_names):
    wins = [0] * len(side_names)
    draws = 0
    timeouts = 0
    for row in rows:
        if row.outcome == 'victory' and 0 <= row.winner_index < len(wins):
            wins[row.winner_index] += 1
        elif row.outcome == 'timeout':
            timeouts += 1
        else:
            draws += 1
    return {
        'done': len(rows),
        'total': int(total),
        'wins': wins,
        'side_names': list(side_names),
        'draws': draws,
        'timeouts': timeouts,
    }


def spawn_scene(snapshot, rng):
    """Новые существа и новая карта. Снимок не меняется."""
    names = side_names_of(snapshot)
    sides = []
    for side_index, row in enumerate(snapshot.get('sides') or []):
        side = []
        for index, data in enumerate(row or []):
            payload = copy.deepcopy(data)
            enemy = Enemy.from_dict(payload)
            enemy.uid = creature_uid(data, side_index, index)
            enemy.moved_ft = payload.get('moved_ft') or 0
            enemy._rng = rng
            enemy._observers = []
            side.append(enemy)
        sides.append(side)
    ignore = {}
    for key, value in (snapshot.get('ignore_sides') or {}).items():
        ignore[int(key)] = {int(item) for item in value}
    battle_map = None
    map_state = snapshot.get('map')
    if map_state:
        battle_map = BattleMap(int(map_state['width']), int(map_state['height']))
        battle_map.load_terrain(map_state.get('terrain'))
        positions = map_state.get('positions') or {}
        for side in sides:
            for enemy in side:
                pos = positions.get(enemy.uid)
                if pos is None:
                    continue
                battle_map.place(enemy, pos[0], pos[1])
    return sides, names, ignore, battle_map


def _add_damage(events, id_to_uid, dealt, taken):
    for event in events:
        total = 0
        for part in getattr(event, 'damages', None) or []:
            try:
                total += int(getattr(part, 'final', 0) or 0)
            except (TypeError, ValueError):
                continue
        if total <= 0:
            continue
        actor = id_to_uid.get(getattr(event, 'actor_id', None))
        target = id_to_uid.get(getattr(event, 'target_id', None))
        if actor is not None:
            dealt[actor] = dealt.get(actor, 0) + total
        if target is not None:
            taken[target] = taken.get(target, 0) + total


def _living_sides(sides):
    return [index for index, side in enumerate(sides)
            if any(getattr(enemy, 'alive', False) for enemy in side)]


def _resistance_left(enemy):
    block = getattr(enemy, 'legendary_resistance', None)
    if not isinstance(block, dict):
        return None
    current = getattr(enemy, 'legendary_resistance_remaining', None)
    if current is None:
        return None
    try:
        return int(current)
    except (TypeError, ValueError):
        return None


def _recharge_ready(enemy):
    state = getattr(enemy, 'recharge_state', None) or {}
    ready = {}
    for name, slot in state.items():
        if isinstance(slot, dict):
            ready[str(name)] = bool(slot.get('ready', True))
    return ready


def run_one(snapshot, *, seed, number=1, max_rounds=40, auto_move=True,
            crit_mode='double_all', quiet=True):
    """Один бой. seed — уже выведенный сид этого боя, не базовый."""
    if int(max_rounds) < 1:
        raise ValueError('лимит раундов должен быть не меньше 1')
    rng = random.Random(int(seed))
    crit_mode = normalize_crit_mode(crit_mode)
    dealt = {}
    taken = {}
    rounds = 0
    outcome = 'timeout'
    winner_index = -1
    with bound(rng):
        sides, names, ignore, battle_map = spawn_scene(snapshot, rng)
        id_to_uid = {}
        roster = []
        for side_index, side in enumerate(sides):
            side_name = names[side_index] if side_index < len(names) else f'Сторона {side_index + 1}'
            for enemy in side:
                id_to_uid[id(enemy)] = enemy.uid
                roster.append((side_index, side_name, enemy))
        engine = DecisionEngine()
        engine.explain = False
        while rounds < int(max_rounds):
            result = run_round(
                sides, names, ignore, battle_map, engine,
                auto_move=bool(auto_move), crit_mode=crit_mode, rng=rng,
                round_no=rounds + 1, quiet=bool(quiet))
            if result.outcome == 'empty':
                outcome = 'draw'
                break
            rounds += 1
            _add_damage(result.events, id_to_uid, dealt, taken)
            living = _living_sides(sides)
            if len(living) <= 1:
                if len(living) == 1:
                    winner_index = living[0]
                    outcome = 'victory'
                else:
                    winner_index = -1
                    outcome = 'draw'
                break
        else:
            living = _living_sides(sides)
            if len(living) == 1:
                winner_index = living[0]
                outcome = 'victory'
            elif len(living) == 0:
                winner_index = -1
                outcome = 'draw'
            else:
                winner_index = -1
                outcome = 'timeout'
        creatures = []
        for side_index, side_name, enemy in roster:
            creatures.append(CreatureEnd(
                uid=enemy.uid,
                name=enemy.name,
                side_index=side_index,
                side_name=side_name,
                hp=int(getattr(enemy, 'hp', 0) or 0),
                alive=bool(getattr(enemy, 'alive', False)),
                dealt=int(dealt.get(enemy.uid, 0)),
                taken=int(taken.get(enemy.uid, 0)),
                resistance_remaining=_resistance_left(enemy),
                recharge_ready=_recharge_ready(enemy),
            ))
    winner = names[winner_index] if 0 <= winner_index < len(names) else ''
    return BattleRow(int(number), int(seed), winner, winner_index, rounds, outcome, creatures)


def _init_worker(snapshot, max_rounds, auto_move, crit_mode):
    global _WORKER
    _WORKER = (snapshot, int(max_rounds), bool(auto_move), crit_mode)


def _chunk_task(jobs):
    snapshot, max_rounds, auto_move, crit_mode = _WORKER
    return [
        run_one(snapshot, seed=seed, number=number, max_rounds=max_rounds,
                auto_move=auto_move, crit_mode=crit_mode)
        for number, seed in jobs
    ]


def _chunk_size(total, workers):
    pieces = max(1, int(workers) * 4)
    return max(1, min(10, total // pieces or 1))


def _slim(snapshot):
    data = dict(snapshot)
    data['events'] = []
    data['engine_log'] = []
    return data


def _run_parallel(snapshot, jobs, workers, max_rounds, auto_move, crit_mode,
                  cancel, on_rows):
    context = multiprocessing.get_context('spawn')
    size = _chunk_size(len(jobs), workers)
    chunks = [jobs[index:index + size] for index in range(0, len(jobs), size)]
    rows = []
    cancelled = False
    pool = context.Pool(
        processes=int(workers),
        initializer=_init_worker,
        initargs=(_slim(snapshot), int(max_rounds), bool(auto_move),
                  normalize_crit_mode(crit_mode)),
    )
    try:
        iterator = pool.imap_unordered(_chunk_task, chunks)
        pending = len(chunks)
        while pending:
            if _is_cancel(cancel):
                cancelled = True
                break
            try:
                part = iterator.next(0.2)
            except (TimeoutError, multiprocessing.TimeoutError):
                continue
            except StopIteration:
                break
            pending -= 1
            rows.extend(part)
            on_rows(rows)
        if _is_cancel(cancel):
            cancelled = True
    finally:
        pool.terminate()
        pool.join()
    return rows, cancelled


def run_batch(snapshot, *, battles=1000, seed=1, max_rounds=40, auto_move=True,
              crit_mode='double_all', workers=1, progress=None, cancel=None):
    """N боёв. progress(dict) зовётся из того же потока, что и run_batch."""
    battles = int(battles)
    max_rounds = int(max_rounds)
    if battles < 1:
        raise ValueError('число боёв должно быть не меньше 1')
    if max_rounds < 1:
        raise ValueError('лимит раундов должен быть не меньше 1')
    if not snapshot or not (snapshot.get('sides') or []):
        raise ValueError('в сцене нет сторон')
    if workers is None or int(workers) < 1:
        workers = os.cpu_count() or 1
    workers = int(workers)
    names = side_names_of(snapshot)
    roster = roster_of(snapshot)
    jobs = [(index + 1, derive_seed(seed, index)) for index in range(battles)]
    stride = 1 if battles <= 400 else 10
    rows = []
    cancelled = False

    def emit(force=False):
        if progress is None:
            return
        done = len(rows)
        if force or done == 1 or done == battles or done % stride == 0:
            progress(_progress_payload(rows, battles, names))

    if _is_cancel(cancel):
        cancelled = True
    elif workers == 1:
        for number, battle_seed in jobs:
            if _is_cancel(cancel):
                cancelled = True
                break
            rows.append(run_one(
                snapshot, seed=battle_seed, number=number, max_rounds=max_rounds,
                auto_move=auto_move, crit_mode=crit_mode))
            emit()
    else:
        def on_rows(current):
            rows[:] = current
            emit()

        parallel_rows, cancelled = _run_parallel(
            snapshot, jobs, workers, max_rounds, auto_move, crit_mode, cancel, on_rows)
        rows = parallel_rows
    if progress is not None:
        progress(_progress_payload(rows, battles, names))
    return aggregate(
        rows, roster, requested=battles, seed=seed, max_rounds=max_rounds,
        workers=workers, cancelled=cancelled, side_names=names)


def make_scene(groups, ignore_sides=None):
    """Снимок из списка {'name', 'type', 'count', 'strategy'}."""
    scene = _Scene()
    for index, group in enumerate(groups):
        name = str(group.get('name') or f'Сторона {chr(65 + index)}')
        kind = str(group.get('type') or 'обычный')
        count = int(group.get('count') if group.get('count') is not None else 1)
        strategy_name = str(group.get('strategy') or 'случайная')
        strategy_cls = _STRATS.get(strategy_name, RandomStrategy)
        scene.side_names.append(name)
        side = []
        for number in range(max(0, count)):
            enemy = EnemyFactory.create_enemy(kind, f'{name}_{number + 1}', index)
            enemy.strategy = strategy_cls()
            side.append(enemy)
        scene.sides.append(side)
        scene.setup.append({
            'name': name, 'type': kind, 'strategy': strategy_name, 'count': count,
        })
    if scene.sides:
        width = max(24, 4 * len(scene.sides))
        zone = max(1, width // len(scene.sides))
        tallest = max((len(side) for side in scene.sides), default=0)
        height = max(16, (tallest + zone - 1) // zone + 2)
        scene.battle_map = BattleMap(width, height)
        scene.battle_map.formation_placement(scene.sides)
    if ignore_sides:
        parsed = {int(key): {int(item) for item in value} for key, value in ignore_sides.items()}
        scene.ignore_sides = parsed
        for side_index, banned in parsed.items():
            if side_index < len(scene.sides):
                for enemy in scene.sides[side_index]:
                    enemy.ignore_sides.update(banned)
    return capture_battle(scene)


def demo_snapshot():
    """Типичная сцена: четыре орка против четырёх гоблинов, оба отряда агрессивны."""
    return make_scene([
        {'name': 'Орки', 'type': 'орк', 'count': 4, 'strategy': 'агрессивная'},
        {'name': 'Гоблины', 'type': 'гоблин', 'count': 4, 'strategy': 'агрессивная'},
    ])


def snapshot_from_sides(sides, side_names, battle_map=None, ignore_sides=None):
    scene = _Scene()
    scene.sides = sides
    scene.side_names = list(side_names)
    scene.battle_map = battle_map
    scene.ignore_sides = ignore_sides or {}
    return capture_battle(scene)


def load_snapshot(path):
    """JSON настроек окна (ключ battle) или сам снимок, или состав сторон."""
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError('файл настроек должен быть объектом JSON')
    battle = data.get('battle')
    if isinstance(battle, dict) and battle.get('sides'):
        snap = copy.deepcopy(battle)
        if data.get('custom_types') and not snap.get('custom_types'):
            snap['custom_types'] = copy.deepcopy(data['custom_types'])
        return snap
    if data.get('sides') and 'side_names' in data:
        return copy.deepcopy(data)
    if data.get('army_types') or data.get('side_names') or data.get('num_sides'):
        return _snapshot_from_settings(data)
    raise ValueError('в файле нет ни сцены боя, ни состава сторон')


def _snapshot_from_settings(data):
    names = list(data.get('side_names') or [])
    counts = list(data.get('side_counts') or [])
    kinds = list(data.get('army_types') or [])
    strategies = list(data.get('strategy_types') or [])
    total = int(data.get('num_sides') or len(names) or len(kinds) or 0)
    groups = []
    for index in range(total):
        groups.append({
            'name': names[index] if index < len(names) and names[index] else f'Сторона {chr(65 + index)}',
            'type': kinds[index] if index < len(kinds) and kinds[index] else 'обычный',
            'count': int(counts[index]) if index < len(counts) and counts[index] is not None else 1,
            'strategy': strategies[index] if index < len(strategies) and strategies[index] else 'случайная',
        })
    saved = dict(EnemyFactory.CUSTOM_TYPES)
    try:
        for name, body in (data.get('custom_types') or {}).items():
            EnemyFactory.CUSTOM_TYPES[name] = body
        return make_scene(groups, data.get('ignore_sides') or None)
    finally:
        EnemyFactory.CUSTOM_TYPES.clear()
        EnemyFactory.CUSTOM_TYPES.update(saved)


def _cell(value):
    if isinstance(value, float):
        text = f'{value:.6f}'.rstrip('0').rstrip('.')
        return text if text not in ('', '-0') else '0'
    return value


def survivors_text(row):
    parts = []
    for creature in row.creatures:
        if creature.alive:
            parts.append(f'{creature.name}={creature.hp}')
    return '; '.join(parts)


def write_csv(path, report):
    """UTF-8 с BOM, разделитель «;» — так файл открывается колонками в Excel."""
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle, delimiter=';')
        writer.writerow(['сводка', 'значение'])
        for key, value in (
            ('боёв', report.battles_done),
            ('запрошено', report.battles_requested),
            ('базовый_сид', report.seed),
            ('лимит_раундов', report.max_rounds),
            ('процессы', report.workers),
            ('отменено', 'да' if report.cancelled else 'нет'),
            ('среднее_раундов', report.mean_rounds),
            ('медиана_раундов', report.median_rounds),
        ):
            writer.writerow([key, _cell(value)])
        writer.writerow([])
        writer.writerow(['исход', 'количество', 'доля', 'интервал_95_низ', 'интервал_95_верх'])
        for stat in list(report.sides) + [report.draw, report.timeout]:
            writer.writerow([stat.name, stat.count, _cell(stat.rate),
                             _cell(stat.ci_low), _cell(stat.ci_high)])
        writer.writerow([])
        writer.writerow(['существо', 'сторона', 'выживание', 'средние_хиты',
                         'хиты_если_выжил', 'урон_нанесён', 'урон_получен'])
        for creature in report.creatures:
            alive = '' if creature.mean_hp_alive is None else _cell(creature.mean_hp_alive)
            writer.writerow([
                creature.name, creature.side_name, _cell(creature.survival),
                _cell(creature.mean_hp), alive,
                _cell(creature.mean_dealt), _cell(creature.mean_taken),
            ])
        writer.writerow([])
        writer.writerow(['раундов', 'боёв'])
        for rounds, count in report.round_histogram:
            writer.writerow([rounds, count])
        writer.writerow([])
        writer.writerow(['номер', 'сид', 'победитель', 'раунды', 'исход', 'хиты_выживших'])
        for row in report.battles:
            writer.writerow([
                row.number, row.seed, row.winner, row.rounds,
                _OUTCOME_RU.get(row.outcome, row.outcome), survivors_text(row),
            ])


def summary_lines(report):
    lines = []
    tail = ' (отменено)' if report.cancelled else ''
    lines.append(f'Боёв: {report.battles_done} из {report.battles_requested}{tail}')
    for side in report.sides:
        lines.append(
            f'{side.name}: {side.count} ({side.rate * 100:.1f}%, '
            f'95% {side.ci_low * 100:.1f}–{side.ci_high * 100:.1f}%)')
    lines.append(f'Ничьи: {report.draw.count} ({report.draw.rate * 100:.1f}%)')
    lines.append(f'Таймауты: {report.timeout.count} ({report.timeout.rate * 100:.1f}%)')
    lines.append(
        f'Раунды: среднее {report.mean_rounds:.2f}, медиана {report.median_rounds:.2f}')
    return lines


def cli(argv=None):
    parser = argparse.ArgumentParser(
        prog='python -m monte_carlo',
        description=('Пакетная симуляция боя без интерфейса. '
                     'CSV в UTF-8 с BOM, колонки через точку с запятой.'),
    )
    parser.add_argument('-n', '--battles', type=int, default=1000,
                        help='число боёв (по умолчанию 1000)')
    parser.add_argument('-s', '--seed', type=int, default=1, help='базовый сид серии')
    parser.add_argument('-r', '--max-rounds', type=int, default=40,
                        help='лимит раундов на бой')
    parser.add_argument('-o', '--csv', required=True, help='куда записать CSV')
    parser.add_argument('--settings',
                        help='JSON настроек или снимок боя; без флага — орки против гоблинов')
    parser.add_argument('--workers', type=int, default=1,
                        help='число процессов; 0 — по числу ядер')
    parser.add_argument('--crit', choices=('double_all', 'dice_only'), default='double_all')
    parser.add_argument('--no-auto-move', action='store_true')
    parser.add_argument('-q', '--quiet', action='store_true', help='не печатать прогресс')
    args = parser.parse_args(argv)
    try:
        snapshot = load_snapshot(args.settings) if args.settings else demo_snapshot()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Не удалось прочитать сцену: {exc}', file=sys.stderr)
        return 2
    cancel = threading.Event()

    def _stop(_signum, _frame):
        cancel.set()
        print('Останавливаюсь после текущего фрагмента…', file=sys.stderr)

    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _stop)

    def progress(payload):
        if args.quiet:
            return
        done = payload['done']
        total = payload['total']
        if done == 1 or done == total or done % 50 == 0:
            print(f'{done}/{total}', file=sys.stderr)

    try:
        report = run_batch(
            snapshot, battles=args.battles, seed=args.seed, max_rounds=args.max_rounds,
            auto_move=not args.no_auto_move, crit_mode=args.crit, workers=args.workers,
            progress=progress, cancel=cancel)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGINT, previous)
    write_csv(args.csv, report)
    print('\n'.join(summary_lines(report)))
    print(f'CSV: {args.csv}')
    return 0


if __name__ == '__main__':
    # python -m запускает файл как __main__. Рабочий процесс должен импортировать
    # monte_carlo._chunk_task, поэтому считаем через обычный импорт модуля.
    from monte_carlo import cli as _cli
    raise SystemExit(_cli())
