"""Пакетная симуляция: сиды, сводка, CSV, отмена, копия сцены."""
import copy
import csv
import io
import json
import os
import random
import tempfile
import threading
import unittest
from contextlib import redirect_stdout

from battle_map_model import BattleMap
from battle_round import run_round
from conditions import apply_condition
from decision_engine import DecisionEngine
from entities import Attack, Enemy
from factory import EnemyFactory
from monte_carlo import (BattleRow, CreatureEnd, aggregate, cli, derive_seed,
                         load_snapshot, make_scene, run_batch, run_one,
                         snapshot_from_sides, spawn_scene, wilson, write_csv)
from rng_channel import bound


def _bite(name='Укус', bonus=8, dice='d4', mod=1):
    return Attack(name, bonus, 1, dice, mod, 'колющий', range_ft=5)


def _pair(left_hp=40, right_hp=40, left_bonus=5, right_bonus=5):
    left = Enemy('Орк', left_hp, 14, [_bite('Секира', left_bonus, 'd8', 3)], 0, speed=30)
    right = Enemy('Гоблин', right_hp, 13, [_bite('Кинжал', right_bonus, 'd6', 2)], 1, speed=30)
    for enemy, dex in ((left, 12), (right, 14)):
        enemy.ability_scores = {'dex': dex, 'int': 10}
        enemy.ability_mods = {'dex': (dex - 10) // 2, 'int': 0}
        enemy.size = 'Средний'
    battle = BattleMap(12, 8)
    battle.place(left, 0, 0)
    battle.place(right, 1, 0)
    return snapshot_from_sides([[left], [right]], ['Орки', 'Гоблины'], battle)


def _breath_scene(*, resistance=False):
    dragon = Enemy('Дракон', 90, 18, [_bite()], 0, speed=30)
    dragon.ability_scores = {'dex': 10, 'str': 16}
    dragon.ability_mods = {'dex': 0, 'str': 3}
    dragon.size = 'Средний'
    dragon.special_actions = [{
        'name': 'Дыхание',
        'effect': {
            'name': 'Дыхание',
            'replaces': True,
            'area': 'cone',
            'range_ft': 30,
            'ability': 'dex',
            'dc': 30,
            'half_on_success': True,
            'damage': {'dice_count': 1, 'dice_type': 'd4', 'modifier': 40,
                       'damage_type': 'огонь'},
            'recharge': {'low': 5, 'high': 6},
            'conditions': [],
        },
    }]
    dragon.legendary_actions = {
        'per_round': 1,
        'options': [{'name': 'Укус', 'cost': 1, 'attack': 'Укус', 'count': 1,
                     'usable': True}],
    }
    victim = Enemy('Жертва', 80, 12, [_bite('Кинжал', 2, 'd4', 0)], 1, speed=30)
    victim.ability_scores = {'dex': 10}
    victim.ability_mods = {'dex': 0}
    victim.size = 'Средний'
    if resistance:
        victim.legendary_resistance = {'count': 3, 'name': 'Легендарное сопротивление'}
        victim.hp = victim.max_hp = 50
    battle = BattleMap(12, 8)
    battle.place(dragon, 0, 0)
    battle.place(victim, 1, 0)
    return snapshot_from_sides([[dragon], [victim]], ['Дракон', 'Жертва'], battle)


def _creature(row, uid):
    return next(item for item in row.creatures if item.uid == uid)


class TestSeedsAndWilson(unittest.TestCase):

    def test_derive_seed_depends_only_on_base_and_index(self):
        first = [derive_seed(10, index) for index in range(6)]
        second = [derive_seed(10, index) for index in range(6)]
        self.assertEqual(first, second)
        self.assertEqual(len(set(first)), 6)
        self.assertEqual(derive_seed(10, 4), first[4])
        self.assertNotEqual(derive_seed(10, 0), derive_seed(11, 0))
        self.assertTrue(all(1 <= seed < 2 ** 31 - 1 for seed in first))

    def test_wilson_bounds(self):
        self.assertEqual(wilson(0, 0), (0.0, 0.0))
        low, high = wilson(0, 20)
        self.assertEqual(low, 0.0)
        self.assertLess(high, 1.0)
        low, high = wilson(20, 20)
        self.assertEqual(high, 1.0)
        self.assertGreater(low, 0.0)
        low, high = wilson(50, 100)
        self.assertAlmostEqual(low, 0.4038, places=3)
        self.assertAlmostEqual(high, 0.5962, places=3)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)


class TestAggregate(unittest.TestCase):

    def _rows(self):
        def end(uid, name, side, hp, alive, dealt, taken):
            side_name = 'Альфа' if side == 0 else 'Бета'
            return CreatureEnd(uid, name, side, side_name, hp, alive, dealt, taken, None)

        def row(number, outcome, winner_index, rounds, creatures):
            winner = {0: 'Альфа', 1: 'Бета'}.get(winner_index, '')
            return BattleRow(number, 500 + number, winner, winner_index, rounds,
                             outcome, creatures)

        specs = [
            (1, 'victory', 0, 1, [(10, True, 8, 1), (0, False, 1, 8)]),
            (2, 'victory', 0, 2, [(0, False, 4, 3), (0, False, 3, 4)]),
            (3, 'victory', 1, 3, [(4, True, 2, 6), (6, True, 6, 2)]),
            (4, 'draw', -1, 4, [(6, True, 1, 5), (0, False, 5, 1)]),
            (5, 'timeout', -1, 4, [(8, True, 0, 0), (9, True, 0, 0)]),
        ]
        rows = []
        for number, outcome, winner, rounds, pair in specs:
            creatures = [
                end('a', 'Альфа_1', 0, pair[0][0], pair[0][1], pair[0][2], pair[0][3]),
                end('b', 'Бета_1', 1, pair[1][0], pair[1][1], pair[1][2], pair[1][3]),
            ]
            rows.append(row(number, outcome, winner, rounds, creatures))
        return rows

    def test_rates_rounds_and_creature_means(self):
        roster = [
            {'uid': 'a', 'name': 'Альфа_1', 'side_index': 0, 'side_name': 'Альфа'},
            {'uid': 'b', 'name': 'Бета_1', 'side_index': 1, 'side_name': 'Бета'},
        ]
        report = aggregate(
            list(reversed(self._rows())), roster, requested=8, seed=7,
            max_rounds=9, workers=1, cancelled=False, side_names=['Альфа', 'Бета'])
        self.assertEqual(report.battles_done, 5)
        self.assertEqual(report.battles_requested, 8)
        self.assertEqual([side.count for side in report.sides], [2, 1])
        self.assertAlmostEqual(report.sides[0].rate, 0.4)
        self.assertEqual(report.draw.count, 1)
        self.assertEqual(report.timeout.count, 1)
        self.assertAlmostEqual(sum(side.rate for side in report.sides)
                               + report.draw.rate + report.timeout.rate, 1.0)
        self.assertLessEqual(report.sides[0].ci_low, report.sides[0].rate)
        self.assertGreaterEqual(report.sides[0].ci_high, report.sides[0].rate)
        self.assertAlmostEqual(report.mean_rounds, 2.8)
        self.assertAlmostEqual(report.median_rounds, 3.0)
        self.assertEqual(report.battles[0].number, 1)
        alpha = report.creatures[0]
        self.assertAlmostEqual(alpha.survival, 0.8)
        self.assertAlmostEqual(alpha.mean_hp, (10 + 0 + 4 + 6 + 8) / 5)
        self.assertAlmostEqual(alpha.mean_hp_alive, (10 + 4 + 6 + 8) / 4)
        self.assertAlmostEqual(alpha.mean_dealt, (8 + 4 + 2 + 1 + 0) / 5)
        self.assertAlmostEqual(alpha.mean_taken, (1 + 3 + 6 + 5 + 0) / 5)
        beta = report.creatures[1]
        self.assertAlmostEqual(beta.survival, 0.4)
        self.assertEqual([item[0] for item in report.round_histogram], [1, 2, 3, 4])
        self.assertEqual([item[1] for item in report.round_histogram], [1, 1, 1, 2])


class TestSimulate(unittest.TestCase):

    def test_same_seed_repeats_and_another_seed_differs(self):
        snap = make_scene([
            {'name': 'Орки', 'type': 'орк', 'count': 3, 'strategy': 'агрессивная'},
            {'name': 'Гоблины', 'type': 'гоблин', 'count': 3, 'strategy': 'агрессивная'},
        ])
        before = copy.deepcopy(snap)
        kwargs = dict(battles=6, max_rounds=12, seed=4, workers=1)
        first = run_batch(snap, **kwargs)
        second = run_batch(snap, **kwargs)
        other = run_batch(snap, battles=6, max_rounds=12, seed=5, workers=1)
        self.assertEqual(snap, before)
        left = [(row.seed, row.winner, row.rounds,
                 [(c.uid, c.hp, c.alive, c.dealt, c.taken) for c in row.creatures])
                for row in first.battles]
        right = [(row.seed, row.winner, row.rounds,
                  [(c.uid, c.hp, c.alive, c.dealt, c.taken) for c in row.creatures])
                 for row in second.battles]
        self.assertEqual(left, right)
        self.assertEqual([row.seed for row in first.battles],
                         [derive_seed(4, index) for index in range(6)])
        again = run_one(snap, seed=first.battles[2].seed, number=3, max_rounds=12)
        self.assertEqual(again.winner, first.battles[2].winner)
        self.assertEqual([(c.uid, c.hp, c.dealt) for c in again.creatures],
                         [(c.uid, c.hp, c.dealt) for c in first.battles[2].creatures])
        other_rows = [(row.winner, row.rounds, tuple(c.hp for c in row.creatures))
                      for row in other.battles]
        self.assertNotEqual(other_rows, [
            (row.winner, row.rounds, tuple(c.hp for c in row.creatures))
            for row in first.battles])

    def test_quiet_matches_verbose_and_skips_log_text(self):
        snap = _pair()
        quiet = run_one(snap, seed=3, max_rounds=4, quiet=True)
        verbose = run_one(snap, seed=3, max_rounds=4, quiet=False)
        self.assertEqual(quiet.winner, verbose.winner)
        self.assertEqual(quiet.rounds, verbose.rounds)
        self.assertEqual([(c.hp, c.dealt, c.taken) for c in quiet.creatures],
                         [(c.hp, c.dealt, c.taken) for c in verbose.creatures])
        def once(quiet_flag):
            rng = random.Random(3)
            with bound(rng):
                sides, names, ignore, battle_map = spawn_scene(snap, rng)
                engine = DecisionEngine()
                result = run_round(
                    sides, names, ignore, battle_map, engine,
                    rng=rng, round_no=1, quiet=quiet_flag)
                hp = [enemy.hp for side in sides for enemy in side]
            return result, hp

        loud, hp_loud = once(False)
        silent, hp_silent = once(True)
        self.assertTrue(loud.text)
        self.assertEqual(silent.text, '')
        self.assertEqual(loud.outcome, silent.outcome)
        self.assertEqual(hp_loud, hp_silent)

    def test_global_random_is_untouched(self):
        snap = _pair()
        random.seed(12345)
        state = random.getstate()
        run_batch(snap, battles=2, seed=8, max_rounds=3, workers=1)
        self.assertEqual(random.getstate(), state)

    def test_round_limit_is_a_timeout(self):
        left = Enemy('Башня', 300, 25, [_bite('Тычок', 0, 'd4', 0)], 0, speed=30)
        right = Enemy('Стена', 300, 25, [_bite('Тычок', 0, 'd4', 0)], 1, speed=30)
        for enemy in (left, right):
            enemy.ability_mods = {'dex': 0}
            enemy.ability_scores = {'dex': 10}
            enemy.size = 'Средний'
        battle = BattleMap(10, 8)
        battle.place(left, 0, 0)
        battle.place(right, 1, 0)
        snap = snapshot_from_sides([[left], [right]], ['А', 'Б'], battle)
        report = run_batch(snap, battles=4, seed=1, max_rounds=3, workers=1)
        self.assertTrue(all(row.outcome == 'timeout' and row.rounds == 3
                            for row in report.battles))
        self.assertEqual(report.timeout.count, 4)
        self.assertEqual(report.sides[0].count, 0)

    def test_stunned_creature_deals_no_damage(self):
        left = Enemy('Орк', 30, 14, [_bite('Секира', 6, 'd8', 4)], 0, speed=30)
        right = Enemy('Гоблин', 20, 12, [_bite('Кинжал', 4, 'd6', 2)], 1, speed=30)
        for enemy in (left, right):
            enemy.ability_mods = {'dex': 1}
            enemy.ability_scores = {'dex': 12}
            enemy.size = 'Средний'
        apply_condition(left, 'stunned')
        battle = BattleMap(10, 8)
        battle.place(left, 0, 0)
        battle.place(right, 1, 0)
        snap = snapshot_from_sides([[left], [right]], ['Орки', 'Гоблины'], battle)
        row = run_one(snap, seed=2, max_rounds=1)
        self.assertEqual(_creature(row, snap['sides'][0][0]['uid']).dealt, 0)
        self.assertEqual(left.hp, 30)
        self.assertTrue(any(item.get('id') == 'stunned' for item in left.conditions))

    def test_breath_recharge_and_legendary_resistance(self):
        ready = _breath_scene()
        cold = copy.deepcopy(ready)
        cold['sides'][0][0]['recharge_state'] = {
            'Дыхание': {'low': 7, 'high': 7, 'ready': False},
        }
        dragon = ready['sides'][0][0]['uid']
        victim = ready['sides'][1][0]['uid']
        fired = run_one(ready, seed=1, max_rounds=1)
        held = run_one(cold, seed=1, max_rounds=1)
        self.assertGreaterEqual(_creature(fired, dragon).dealt, 41)
        self.assertLessEqual(_creature(held, dragon).dealt, 20)
        self.assertGreaterEqual(_creature(fired, dragon).dealt,
                                _creature(held, dragon).dealt + 20)
        self.assertFalse(_creature(fired, dragon).recharge_ready.get('Дыхание', True))
        self.assertFalse(_creature(held, dragon).recharge_ready.get('Дыхание', True))
        self.assertNotIn('Дыхание', ready['sides'][0][0].get('recharge_state') or {})

        shielded = _breath_scene(resistance=True)
        plain = copy.deepcopy(shielded)
        plain['sides'][1][0]['legendary_resistance'] = None
        plain['sides'][1][0]['legendary_resistance_remaining'] = None
        with_save = run_one(shielded, seed=1, max_rounds=1)
        without = run_one(plain, seed=1, max_rounds=1)
        uid = shielded['sides'][1][0]['uid']
        self.assertEqual(_creature(with_save, uid).resistance_remaining, 2)
        self.assertIsNone(_creature(without, uid).resistance_remaining)
        self.assertGreater(_creature(with_save, uid).hp, _creature(without, uid).hp)
        self.assertIsNone(shielded['sides'][1][0].get('legendary_resistance_remaining'))


class TestCsvAndCancel(unittest.TestCase):

    def test_csv_bom_sections_and_battle_rows(self):
        snap = _pair(left_hp=18, right_hp=14)
        report = run_batch(snap, battles=3, seed=11, max_rounds=6, workers=1)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'бои.csv')
            write_csv(path, report)
            with open(path, 'rb') as handle:
                raw = handle.read()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        text = raw.decode('utf-8-sig')
        blocks = []
        current = []
        for line in text.splitlines():
            if line.strip() == '':
                if current:
                    blocks.append(current)
                    current = []
            else:
                current.append(line)
        if current:
            blocks.append(current)
        self.assertEqual(len(blocks), 5)
        summary = list(csv.reader(blocks[0], delimiter=';'))
        self.assertEqual(summary[0], ['сводка', 'значение'])
        as_map = {row[0]: row[1] for row in summary[1:]}
        self.assertEqual(as_map['боёв'], '3')
        self.assertEqual(as_map['базовый_сид'], '11')
        self.assertEqual(as_map['отменено'], 'нет')
        self.assertEqual(len(summary[1][0].split(',')), 1)
        outcomes = list(csv.reader(blocks[1], delimiter=';'))
        self.assertEqual(outcomes[0][0], 'исход')
        names = [row[0] for row in outcomes[1:]]
        self.assertEqual(names[:2], ['Орки', 'Гоблины'])
        self.assertEqual(names[-2:], ['ничья', 'таймаут'])
        battles = list(csv.reader(blocks[4], delimiter=';'))
        self.assertEqual(battles[0], ['номер', 'сид', 'победитель', 'раунды', 'исход',
                                      'хиты_выживших'])
        self.assertEqual(len(battles) - 1, 3)
        self.assertEqual(int(battles[1][0]), 1)
        self.assertEqual(int(battles[1][1]), report.battles[0].seed)
        self.assertIn(battles[1][4], ('победа', 'ничья', 'таймаут'))

    def test_cancel_stops_between_battles(self):
        snap = _pair()
        preset = threading.Event()
        preset.set()
        stopped = run_batch(snap, battles=10, seed=1, max_rounds=2, cancel=preset)
        self.assertTrue(stopped.cancelled)
        self.assertEqual(stopped.battles_done, 0)

        cancel = threading.Event()

        def progress(payload):
            if payload['done'] >= 2:
                cancel.set()

        report = run_batch(snap, battles=30, seed=2, max_rounds=2,
                           progress=progress, cancel=cancel, workers=1)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.battles_done, 2)
        self.assertEqual(len(report.battles), 2)

    def test_workers_match_one_process(self):
        snap = _pair(left_hp=16, right_hp=16)
        single = run_batch(snap, battles=4, seed=9, max_rounds=5, workers=1)
        multi = run_batch(snap, battles=4, seed=9, max_rounds=5, workers=2)
        def packed(report):
            return [(row.number, row.seed, row.winner, row.rounds,
                     tuple((c.uid, c.hp, c.dealt, c.taken) for c in row.creatures))
                    for row in report.battles]
        self.assertEqual(packed(single), packed(multi))
        self.assertFalse(multi.cancelled)

    def test_cli_writes_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = os.path.join(tmp, 'сцена.json')
            with open(settings, 'w', encoding='utf-8') as handle:
                json.dump({
                    'num_sides': 2,
                    'side_names': ['А', 'Б'],
                    'side_counts': [1, 1],
                    'army_types': ['орк', 'гоблин'],
                    'strategy_types': ['агрессивная', 'агрессивная'],
                }, handle)
            before = copy.deepcopy(EnemyFactory.CUSTOM_TYPES)
            out = os.path.join(tmp, 'итог.csv')
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cli(['-n', '2', '-s', '6', '-r', '8', '-o', out,
                            '--settings', settings, '-q'])
            self.assertEqual(code, 0)
            self.assertEqual(EnemyFactory.CUSTOM_TYPES, before)
            self.assertIn('Боёв: 2', buffer.getvalue())
            with open(out, 'rb') as handle:
                self.assertTrue(handle.read().startswith(b'\xef\xbb\xbf'))
            loaded = load_snapshot(settings)
            self.assertEqual(len(loaded['sides']), 2)
            self.assertEqual(len(loaded['sides'][0]), 1)


class TestQuietRound(unittest.TestCase):

    def test_damage_tally_matches_event_finals(self):
        snap = _pair()
        row = run_one(snap, seed=15, number=1, max_rounds=3)
        rng = random.Random(15)
        dealt = {}
        with bound(rng):
            sides, names, ignore, battle_map = spawn_scene(snap, rng)
            id_to_uid = {id(enemy): enemy.uid for side in sides for enemy in side}
            engine = DecisionEngine()
            engine.explain = False
            for round_no in range(1, 4):
                result = run_round(sides, names, ignore, battle_map, engine,
                                   rng=rng, round_no=round_no, quiet=True)
                for event in result.events:
                    total = sum(int(getattr(part, 'final', 0) or 0)
                                for part in (event.damages or []))
                    actor = id_to_uid.get(event.actor_id)
                    if actor is not None and total:
                        dealt[actor] = dealt.get(actor, 0) + total
                if result.outcome != 'continue':
                    break
        for creature in row.creatures:
            self.assertEqual(creature.dealt, dealt.get(creature.uid, 0))
