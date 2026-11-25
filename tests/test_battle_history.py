"""Отмена и повтор снимка боя. Без Qt."""
import json
import random
import time
import unittest
from unittest import mock

from battle_history import BattleHistory, apply_snapshot, capture_battle
from battle_map_model import BattleMap
from battle_round import run_round
from combat_log import CombatEvent, render_log
from decision_engine import DecisionEngine
from entities import Attack, Enemy
from factory import EnemyFactory
from observer import Observer


class MaxRng:
    def randint(self, a, b):
        return b


class BoomRng:
    def randint(self, a, b):
        raise AssertionError('повтор не должен бросать кости')


class Doc:
    def __init__(self):
        self.sides = []
        self.side_names = []
        self.ignore_sides = {}
        self.alliance_settings = []
        self.battle_map = None
        self.battle_events = []
        self.round_no = 0
        self.engine = DecisionEngine()
        self.setup = []
        self.selected = None


def _axe(name='Топор'):
    return Attack(name, 5, 1, 'd12', 3, 'рубящий')


def _fighter(name, side, hp=40, speed=30):
    enemy = Enemy(name, hp, 12, [_axe()], side, speed=speed, rng=MaxRng())
    enemy.ability_scores = {'str': 16, 'dex': 14, 'int': 10}
    enemy.ability_mods = {'str': 3, 'dex': 2, 'int': 0}
    enemy.size = 'Средний'
    return enemy


class TestBattleHistory(unittest.TestCase):

    def setUp(self):
        self._types = json.loads(json.dumps(EnemyFactory.CUSTOM_TYPES))

    def tearDown(self):
        EnemyFactory.CUSTOM_TYPES.clear()
        EnemyFactory.CUSTOM_TYPES.update(self._types)

    def _pair(self):
        doc = Doc()
        left = _fighter('Орк 3', 0)
        right = _fighter('Эльф 1', 1, hp=30)
        doc.sides = [[left], [right]]
        doc.side_names = ['Орки', 'Эльфы']
        doc.setup = [
            {'name': 'Орки', 'type': 'орк', 'strategy': 'агрессивная', 'count': 1},
            {'name': 'Эльфы', 'type': 'эльф', 'strategy': 'случайная', 'count': 1},
        ]
        doc.battle_map = BattleMap(16, 8)
        doc.battle_map.place(left, 0, 0)
        doc.battle_map.place(right, 1, 0)
        doc.selected = left
        return doc, left, right

    def test_add_and_remove_creature_and_side(self):
        doc, left, _right = self._pair()
        history = BattleHistory()
        before = capture_battle(doc)
        extra = _fighter('Орк 4', 0)
        doc.sides[0].append(extra)
        doc.setup[0]['count'] = 2
        history.commit('добавление существа', before, capture_battle(doc))
        self.assertFalse(history.commit(
            'пустая правка', capture_battle(doc), capture_battle(doc)))

        side_before = capture_battle(doc)
        newbie = _fighter('Гном 1', 2, hp=10)
        doc.sides.append([newbie])
        doc.side_names.append('Гномы')
        doc.setup.append({'name': 'Гномы', 'type': 'гном', 'strategy': 'защитная', 'count': 1})
        history.commit('добавление стороны', side_before, capture_battle(doc))

        apply_snapshot(history.undo(), doc)
        self.assertEqual([enemy.name for enemy in doc.sides[0]], ['Орк 3', 'Орк 4'])
        self.assertEqual(doc.side_names, ['Орки', 'Эльфы'])
        apply_snapshot(history.undo(), doc)
        self.assertEqual([enemy.name for enemy in doc.sides[0]], ['Орк 3'])
        self.assertIs(doc.sides[0][0], left)
        apply_snapshot(history.redo(), doc)
        self.assertEqual([enemy.name for enemy in doc.sides[0]], ['Орк 3', 'Орк 4'])
        self.assertIs(doc.sides[0][0], left)

    def test_edit_characteristics_roundtrip(self):
        doc, left, _right = self._pair()
        seen = []

        class Watch(Observer):
            def update(self, subject):
                seen.append(subject.hp)

        left.attach(Watch())
        rng = left._rng
        history = BattleHistory()
        before = capture_battle(doc)
        left.name = 'Орк-вождь'
        left.ac = 18
        left.max_hp = 50
        left.hp = 22
        left.speed = 40
        left.attacks = [Attack('Секира', 7, 2, 'd8', 4, 'рубящий', 5, True)]
        left.ability_scores = {'str': 18, 'dex': 10, 'int': 8}
        left.condition_immunities = ['испуг']
        left.size = 'Большой'
        left.legendary_actions = {
            'per_round': 2,
            'options': [{'name': 'Секира', 'cost': 1, 'attack': 'Секира', 'usable': True}],
        }
        left.legendary_remaining = 2
        history.commit('правка: Орк 3', before, capture_battle(doc))
        saved = capture_battle(doc)

        apply_snapshot(history.undo(), doc)
        self.assertIs(doc.sides[0][0], left)
        self.assertIs(left._rng, rng)
        self.assertEqual(left.name, 'Орк 3')
        self.assertEqual(left.ac, 12)
        self.assertEqual(left.attacks[0].name, 'Топор')
        self.assertEqual(left.condition_immunities, [])
        self.assertIsNone(left.legendary_actions)
        left.take_damage(1)
        self.assertEqual(seen, [left.hp])

        apply_snapshot(history.redo(), doc)
        self.assertEqual(capture_battle(doc), saved)
        self.assertEqual(left.ac, 18)
        self.assertTrue(left.attacks[0].magical)
        self.assertEqual(left.legendary_remaining, 2)
        self.assertEqual(left.size, 'Большой')
        # правка живого объекта не портит снимок повтора
        left.hp = 1
        left.legendary_actions['per_round'] = 9
        apply_snapshot(history.undo(), doc)
        apply_snapshot(history.redo(), doc)
        self.assertEqual(left.hp, 22)
        self.assertEqual(left.legendary_actions['per_round'], 2)

    def test_move_and_placement_redo_does_not_reroll(self):
        doc, left, right = self._pair()
        history = BattleHistory()
        before = capture_battle(doc)
        doc.battle_map.place(left, 4, 2)
        left.moved_ft = 20
        doc.selected = left
        history.commit('ход Орк 3', before, capture_battle(doc))
        placed = capture_battle(doc)

        apply_snapshot(history.undo(), doc)
        self.assertEqual(doc.battle_map.get_pos(left), (0, 0))
        self.assertEqual(left.moved_ft, 0)
        self.assertIs(doc.selected, left)

        left._rng = BoomRng()
        right._rng = BoomRng()
        with mock.patch('random.randint', side_effect=AssertionError('кости')), \
                mock.patch('random.random', side_effect=AssertionError('кости')):
            apply_snapshot(history.redo(), doc)
        self.assertEqual(capture_battle(doc), placed)
        self.assertEqual(doc.battle_map.get_pos(left), (4, 2))
        self.assertEqual(left.moved_ft, 20)

        random.seed(1)
        scattered = capture_battle(doc)
        doc.battle_map.random_placement(doc.sides)
        history.commit('случайная расстановка', scattered, capture_battle(doc))
        after_scatter = capture_battle(doc)
        apply_snapshot(history.undo(), doc)
        with mock.patch('random.shuffle', side_effect=AssertionError('перестановка')):
            apply_snapshot(history.redo(), doc)
        self.assertEqual(capture_battle(doc), after_scatter)

    def test_alliances(self):
        doc, left, right = self._pair()
        third = _fighter('Гном 1', 2, hp=10)
        doc.sides.append([third])
        doc.side_names.append('Гномы')
        doc.battle_map.place(third, 3, 0)
        history = BattleHistory()
        before = capture_battle(doc)
        doc.alliance_settings = [
            [False, True, False],
            [True, False, False],
            [False, False, False],
        ]
        doc.ignore_sides = {0: {1}, 1: {0}, 2: set()}
        left.ignore_sides.add(1)
        right.ignore_sides.add(0)
        history.commit('альянсы', before, capture_battle(doc))
        apply_snapshot(history.undo(), doc)
        self.assertEqual(doc.ignore_sides, {})
        self.assertEqual(left.ignore_sides, set())
        self.assertEqual(doc.alliance_settings, [])
        apply_snapshot(history.redo(), doc)
        self.assertEqual(doc.ignore_sides[0], {1})
        self.assertEqual(left.ignore_sides, {1})
        self.assertTrue(doc.alliance_settings[0][1])

    def test_bestiary_import_restores_registry(self):
        doc, _left, _right = self._pair()
        history = BattleHistory()
        before = capture_battle(doc)
        EnemyFactory.register_type(
            'Вампир тест', hp=144, ac=16,
            attacks=[{'name': 'Укус', 'attack_bonus': 9, 'damage_dice_count': 1,
                      'damage_dice_type': 'd6', 'damage_modifier': 4,
                      'damage_type': 'колющий'}],
            speed=30, size='Средний', ctype='нежить')
        vampire = EnemyFactory.create_enemy('Вампир тест', 'Вампир 1', 0)
        doc.sides[0].append(vampire)
        doc.setup[0] = {'name': 'Орки', 'type': 'Вампир тест', 'strategy': 'агрессивная',
                        'count': 2}
        history.commit('состав: Вампир тест', before, capture_battle(doc))
        apply_snapshot(history.undo(), doc)
        self.assertNotIn('Вампир тест', EnemyFactory.CUSTOM_TYPES)
        self.assertEqual([enemy.name for enemy in doc.sides[0]], ['Орк 3'])
        apply_snapshot(history.redo(), doc)
        self.assertEqual(EnemyFactory.CUSTOM_TYPES['Вампир тест']['hp'], 144)
        self.assertEqual(doc.sides[0][1].name, 'Вампир 1')
        self.assertEqual(doc.sides[0][1].ac, 16)

    def test_round_undo_restores_exact_state_and_redo_does_not_roll(self):
        doc, left, right = self._pair()
        right.legendary_actions = {
            'per_round': 1,
            'options': [{'name': 'Укус', 'cost': 1, 'desc': 'укус',
                         'attack': 'Топор', 'count': 1, 'usable': True}],
        }
        right.regen = 5
        left.regen = 4
        doc.battle_events = [CombatEvent(kind='note', text='Армии созданы.')]
        history = BattleHistory()
        before = capture_battle(doc)
        hp_before = (left.hp, right.hp)
        pos_before = (doc.battle_map.get_pos(left), doc.battle_map.get_pos(right))

        result = run_round(
            doc.sides, doc.side_names, doc.ignore_sides, doc.battle_map, doc.engine,
            auto_move=True, rng=MaxRng(), round_no=1)
        doc.round_no = 1
        doc.battle_events.extend(result.events)
        after = capture_battle(doc)
        self.assertNotEqual(after, before)
        self.assertNotEqual((left.hp, right.hp), hp_before)
        self.assertIsNotNone(right.legendary_remaining)
        history.commit('раунд 1', before, after)

        apply_snapshot(history.undo(), doc)
        self.assertEqual(capture_battle(doc), before)
        self.assertEqual(doc.round_no, 0)
        self.assertEqual((left.hp, right.hp), hp_before)
        self.assertEqual((doc.battle_map.get_pos(left), doc.battle_map.get_pos(right)), pos_before)
        self.assertIsNone(right.legendary_remaining)
        self.assertEqual(left.moved_ft, 0)
        self.assertEqual(render_log(doc.battle_events), 'Армии созданы.')
        self.assertEqual(doc.engine.get_round_log(), [])

        for side in doc.sides:
            for enemy in side:
                enemy._rng = BoomRng()
        with mock.patch('random.randint', side_effect=AssertionError('кости')), \
                mock.patch('random.random', side_effect=AssertionError('кости')), \
                mock.patch('random.shuffle', side_effect=AssertionError('кости')):
            apply_snapshot(history.redo(), doc)
        self.assertEqual(capture_battle(doc), after)
        self.assertEqual(doc.round_no, 1)
        self.assertEqual(render_log(doc.battle_events), render_log(
            [CombatEvent.from_dict(item) for item in after['events']]))
        self.assertTrue(doc.engine.get_round_log())
        self.assertEqual(right.legendary_remaining, after['sides'][1][0]['legendary_remaining'])

    def test_history_limit_and_branching(self):
        doc, left, _right = self._pair()
        history = BattleHistory(limit=3)
        labels = []
        for hp in (39, 38, 37, 36, 35):
            before = capture_battle(doc)
            left.hp = hp
            label = f'хиты {hp}'
            labels.append(label)
            history.commit(label, before, capture_battle(doc))
        self.assertEqual(len(history), 3)
        self.assertEqual(history.undo_label(), 'хиты 35')
        apply_snapshot(history.undo(), doc)
        apply_snapshot(history.undo(), doc)
        apply_snapshot(history.undo(), doc)
        # Шаги «хиты 39» и «хиты 38» уже вытеснены лимитом: ниже 38 не спуститься.
        self.assertEqual(left.hp, 38)
        self.assertFalse(history.can_undo())
        with self.assertRaises(IndexError):
            history.undo()

        apply_snapshot(history.redo(), doc)
        self.assertEqual(left.hp, 37)
        apply_snapshot(history.undo(), doc)
        before = capture_battle(doc)
        left.hp = 10
        history.commit('другая ветка', before, capture_battle(doc))
        self.assertFalse(history.can_redo())
        self.assertIsNone(history.redo_label())
        apply_snapshot(history.undo(), doc)
        self.assertEqual(left.hp, 38)

    def test_snapshot_is_json_and_limit_constant(self):
        doc, _left, _right = self._pair()
        blob = json.dumps(capture_battle(doc), ensure_ascii=False)
        other = Doc()
        other.engine = doc.engine
        apply_snapshot(json.loads(blob), other)
        self.assertEqual(capture_battle(other), json.loads(blob))

    def test_snapshot_of_two_hundred_units_is_small(self):
        doc = Doc()
        sides = [[], []]
        doc.side_names = ['А', 'Б']
        doc.battle_map = BattleMap(40, 12)
        doc.engine = DecisionEngine()
        for index in range(200):
            enemy = _fighter(f'Орк {index}', index % 2, hp=15)
            enemy.traits = [{'name': 'Ярость', 'desc': 'Остаётся на ногах. ' * 8}]
            enemy.resistances = ['некротический']
            enemy.languages = ['общий', 'оркский']
            sides[index % 2].append(enemy)
            doc.battle_map.place(enemy, (index // 2) % 20, (index // 2) // 20 + (index % 2) * 6)
        doc.sides = sides
        result = run_round(
            doc.sides, doc.side_names, {}, doc.battle_map, doc.engine,
            auto_move=False, rng=MaxRng(), round_no=1)
        doc.round_no = 1
        doc.battle_events.extend(result.events)

        samples = []
        for _ in range(8):
            started = time.perf_counter()
            snap = capture_battle(doc)
            samples.append(time.perf_counter() - started)
        started = time.perf_counter()
        apply_snapshot(snap, doc)
        restore_s = time.perf_counter() - started
        size = len(json.dumps(snap))
        median = sorted(samples)[len(samples) // 2]
        print(f'\nSNAPSHOT 200 after round: {median * 1000:.2f} ms, '
              f'json {size / 1024:.1f} KiB, restore {restore_s * 1000:.2f} ms, '
              f'events {len(doc.battle_events)}')
        self.assertLess(median, 0.08, f'снимок {median * 1000:.1f} мс')
        self.assertLess(restore_s, 0.08, f'восстановление {restore_s * 1000:.1f} мс')
        self.assertGreater(len(doc.battle_events), 100)


if __name__ == '__main__':
    unittest.main(verbosity=2)
