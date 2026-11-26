"""Замер большого боя: раунд, карта, список, журнал, путь/LOS, снимок undo.

Запуск из корня репозитория:

    QT_QPA_PLATFORM=offscreen python3 tools/bench_large_battle.py
    QT_QPA_PLATFORM=offscreen python3 tools/bench_large_battle.py --counts 60 --profile

Пишет JSON в stdout и, с --out, в файл. Seed фиксирован: результаты раунда
не зависят от числа повторов замера.
"""
import argparse
import cProfile
import hashlib
import io
import json
import os
import pstats
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from battle_history import capture_battle
from battle_map_model import BattleMap
from decision_engine import DecisionEngine
from factory import EnemyFactory
import battle_round


SEED = 20261126


def map_size(count, sides=2):
    """Та же формула, что у «Создать армии»: ширина от числа сторон, высота от отряда."""
    per = max(1, (count + sides - 1) // sides)
    map_w = max(24, 4 * sides)
    zone_cols = max(1, map_w // sides)
    map_h = max(16, (per + zone_cols - 1) // zone_cols + 2)
    return map_w, map_h


def paint_terrain(battle_map, salt):
    """Стена с проходами по центру, трудная местность и укрытия. Отдельный ГПСЧ."""
    rng = random.Random(SEED + salt)
    mid = battle_map.width // 2
    for y in range(battle_map.height):
        if y % 3 != 1:
            battle_map.set_terrain(mid, y, 'wall')
        if y % 4 == 0:
            battle_map.set_terrain(max(0, mid - 3), y, 'difficult')
        if y % 5 == 0:
            battle_map.set_terrain(min(battle_map.width - 1, mid + 3), y, 'half')
        if y % 6 == 0:
            battle_map.set_terrain(max(0, mid - 5), y, 'three_quarters')
    for _ in range(max(4, battle_map.height // 2)):
        x = rng.randrange(1, battle_map.width - 1)
        y = rng.randrange(0, battle_map.height)
        if x == mid:
            continue
        battle_map.set_terrain(x, y, rng.choice(('difficult', 'water', 'half', 'total')))


def build_battle(count, terrain):
    """Две стороны гоблинов строем. Гоблин бьёт и вблизи, и из лука — путь и LOS нужны."""
    sides_n = 2
    names = ['Алая', 'Синяя']
    per = [count // sides_n, count - count // sides_n]
    sides = []
    for index, size in enumerate(per):
        side = []
        for number in range(size):
            enemy = EnemyFactory.create_enemy('гоблин', f'{names[index]}_{number + 1}', index)
            side.append(enemy)
        sides.append(side)
    width, height = map_size(count, sides_n)
    battle_map = BattleMap(width, height)
    if terrain:
        paint_terrain(battle_map, count)
    battle_map.formation_placement(sides)
    return sides, names, battle_map


def battle_fingerprint(sides, events):
    rows = []
    for side in sides:
        for enemy in side:
            conds = tuple(
                (item.get('id'), item.get('level'), item.get('rounds'))
                for item in (getattr(enemy, 'conditions', None) or [])
                if isinstance(item, dict))
            rows.append((enemy.name, enemy.hp, bool(enemy.alive), enemy.pos,
                         int(getattr(enemy, 'moved_ft', 0) or 0), conds))
    texts = tuple(getattr(event, 'text', '') for event in events)
    kinds = tuple((getattr(event, 'kind', ''), getattr(event, 'result', ''),
                   getattr(event, 'actor', ''), getattr(event, 'target', ''))
                  for event in events)
    return {'rows': rows, 'texts': texts, 'kinds': kinds}


def run_once(count, terrain):
    random.seed(SEED)
    sides, names, battle_map = build_battle(count, terrain)
    engine = DecisionEngine()
    result = battle_round.run_round(
        sides, names, {}, battle_map, engine, auto_move=True,
        crit_mode='double_all', round_no=1)
    return sides, names, battle_map, result


def time_call(fn, repeats=1):
    samples = []
    value = None
    for _ in range(repeats):
        started = time.perf_counter()
        value = fn()
        samples.append(time.perf_counter() - started)
    return min(samples), value


def measure_combat(count, terrain, repeats):
    def go():
        return run_once(count, terrain)

    best, packed = time_call(go, repeats)
    sides, _names, battle_map, result = packed
    fingerprint = battle_fingerprint(sides, result.events)
    digest = hashlib.sha256(
        json.dumps(fingerprint, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
    # Поиск пути и LOS — на копии расстановки до хода, чтобы не сдвигать кости боя.
    random.seed(SEED)
    sides, _names, battle_map = build_battle(count, terrain)
    attackers = [enemy for side in sides for enemy in side if enemy.alive][:8]
    targets = [enemy for side in sides for enemy in side if enemy.alive
               if enemy.side != attackers[0].side][:12]

    def paths():
        for attacker in attackers:
            for target in targets:
                battle_map.find_path(attacker, target, 6, reach_ft=5)
                if terrain:
                    battle_map.combat_cover(attacker, target)
                    battle_map.can_reach_shot(attacker, target, 30, 80)

    path_best, _ = time_call(paths, repeats)

    doc = type('Doc', (), {})()
    doc.sides = sides
    doc.side_names = _names
    doc.battle_map = battle_map
    doc.ignore_sides = {}
    doc.alliance_settings = []
    doc.round_no = 1
    doc.battle_events = result.events
    doc.engine = DecisionEngine()
    doc.selected = sides[0][0]
    doc.cards = None
    doc.setup = []

    def snap():
        return capture_battle(doc)

    snap_best, snapshot = time_call(snap, repeats)
    warm_best, _warm = time_call(snap, repeats)
    fought = packed[0]
    return {
        'count': count,
        'terrain': terrain,
        'map': [battle_map.width, battle_map.height],
        'placed': sum(1 for side in sides for enemy in side if battle_map.get_pos(enemy)),
        'alive_after_round': sum(1 for side in fought for enemy in side if enemy.alive),
        'events': len(result.events),
        'round_s': round(best, 4),
        'path_los_s': round(path_best, 4),
        'path_queries': len(attackers) * len(targets),
        'snapshot_s': round(snap_best, 4),
        'snapshot_warm_s': round(warm_best, 4),
        'snapshot_bytes': len(json.dumps(snapshot, ensure_ascii=False)),
        'sha256': digest,
        '_events': result.events,
        '_sides': sides,
        '_names': _names,
    }


def measure_ui(count, terrain, repeats, events, sides, names):
    from PyQt6.QtWidgets import QApplication
    from qt_app import MainWindow
    from qt_combat_log import CombatLogPanel

    app = QApplication.instance() or QApplication([])
    random.seed(SEED)
    placed, roster_names, battle_map = build_battle(count, terrain)
    win = MainWindow()
    win.sides = placed
    win.side_names = roster_names
    win.ignore_sides = {}
    win.battle_map = battle_map
    win.resize(1400, 900)
    win.show()
    app.processEvents()

    def redraw():
        win.map_view.rebuild(battle_map, placed, placed[0][0])
        app.processEvents()

    # Холодная сборка сцены и тёплая — то, что делает интерфейс после раунда.
    cold, _ = time_call(redraw, 1)
    warm, _ = time_call(redraw, repeats)

    def roster():
        win.rebuild_battle_lists()
        app.processEvents()

    roster_s, _ = time_call(roster, repeats)

    panel = CombatLogPanel()
    panel.set_roster(sides, roster_names)

    def journal():
        panel.clear()
        panel.append_round(events)
        app.processEvents()

    journal_s, _ = time_call(journal, repeats)
    win.close()
    return {
        'redraw_cold_s': round(cold, 4),
        'redraw_s': round(warm, 4),
        'roster_s': round(roster_s, 4),
        'journal_s': round(journal_s, 4),
    }


def profile_round(count, terrain):
    random.seed(SEED)
    sides, names, battle_map = build_battle(count, terrain)
    engine = DecisionEngine()
    profiler = cProfile.Profile()
    profiler.enable()
    battle_round.run_round(
        sides, names, {}, battle_map, engine, auto_move=True,
        crit_mode='double_all', round_no=1)
    profiler.disable()
    buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=buffer).sort_stats('cumulative')
    stats.print_stats(25)
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description='Замер большого боя')
    parser.add_argument('--counts', default='60,100,150')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--no-ui', action='store_true')
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--fingerprint', action='store_true',
                        help='Печать отпечатка раунда (60, с рельефом и без)')
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    counts = [int(part) for part in args.counts.split(',') if part.strip()]
    rows = []
    for count in counts:
        for terrain in (False, True):
            print(f'# бой {count}, рельеф={terrain}', file=sys.stderr, flush=True)
            row = measure_combat(count, terrain, args.repeats)
            events = row.pop('_events')
            fought_sides = row.pop('_sides')
            fought_names = row.pop('_names')
            if not args.no_ui:
                row.update(measure_ui(
                    count, terrain, max(1, args.repeats), events, fought_sides, fought_names))
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), file=sys.stderr, flush=True)
    if args.profile:
        print(profile_round(counts[0], True))
    if args.fingerprint:
        for terrain in (False, True):
            sides, _names, _bm, result = run_once(60, terrain)
            fp = battle_fingerprint(sides, result.events)
            blob = json.dumps(fp, ensure_ascii=False, default=str)
            import hashlib
            digest = hashlib.sha256(blob.encode('utf-8')).hexdigest()
            print(json.dumps({
                'count': 60, 'terrain': terrain, 'sha256': digest,
                'events': len(result.events),
                'alive': sum(1 for side in sides for enemy in side if enemy.alive),
            }, ensure_ascii=False))
    payload = {'seed': SEED, 'rows': rows}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as handle:
            handle.write(text)
    print(text)


if __name__ == '__main__':
    main()
