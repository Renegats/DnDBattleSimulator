"""Рельеф, линия обзора, укрытие, стоимость шага и снимок карты."""
import json
import os
import random
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication

from battle_history import BattleHistory, apply_snapshot, capture_battle
from battle_map_model import BattleMap
from battle_round import run_round
from battle_strategies import AggressiveStrategy
from combat_core import execute_strikes
from decision_engine import DecisionEngine
from effects import execute_effect
from entities import Attack, Enemy
from monte_carlo import load_snapshot, run_one, snapshot_from_sides, spawn_scene
from qt_app import MainWindow
from terrain import (COVER_HALF, COVER_NONE, COVER_THREE_QUARTERS, COVER_TOTAL,
                     cover_against)


class Roll:
    def __init__(self, *values):
        self.values = list(values)

    def randint(self, a, b):
        if not self.values:
            return a
        return self.values.pop(0)


def fighter(name, side, *, speed=30, hp=20, reach=5, ac=10, bonus=5):
    attack = Attack(name.split()[0], bonus, 1, 'd6', 2, 'колющий', range_ft=reach)
    unit = Enemy(name, hp, ac, [attack], side, speed=speed, rng=random.Random(1))
    unit.size = 'Средний'
    unit.strategy = AggressiveStrategy()
    unit.ability_scores = {'dex': 10, 'int': 10}
    unit.ability_mods = {'dex': 0, 'int': 0}
    return unit


def seal_row(battle_map, y, width):
    for x in range(width):
        battle_map.set_terrain(x, y, 'wall')


class TestCoverGeometry(unittest.TestCase):

    def test_open_ground_has_no_cover(self):
        self.assertEqual(cover_against((0, 0), 1, (3, 0), 1, {}), COVER_NONE)
        self.assertEqual(cover_against((0, 0), 1, (1, 0), 1, {}), COVER_NONE)

    def test_wall_between_is_total_cover(self):
        self.assertEqual(
            cover_against((0, 0), 1, (2, 0), 1, {(1, 0): 'wall'}), COVER_TOTAL)

    def test_cover_cells_grant_their_bonus_to_the_occupant(self):
        self.assertEqual(
            cover_against((0, 0), 1, (3, 0), 1, {(3, 0): 'half'}), COVER_HALF)
        self.assertEqual(
            cover_against((0, 0), 1, (3, 0), 1, {(3, 0): 'three_quarters'}),
            COVER_THREE_QUARTERS)
        self.assertEqual(
            cover_against((0, 0), 1, (3, 0), 1, {(3, 0): 'total'}), COVER_TOTAL)

    def test_creature_on_the_line_is_only_half_cover(self):
        self.assertEqual(
            cover_against((0, 0), 1, (2, 0), 1, {}, creature_cells={(1, 0)}),
            COVER_HALF)
        self.assertEqual(
            cover_against((0, 0), 1, (2, 0), 1, {}), COVER_NONE)

    def test_three_quarters_cell_between_does_not_forbid_the_target(self):
        self.assertEqual(
            cover_against((0, 0), 1, (2, 0), 1, {(1, 0): 'three_quarters'}),
            COVER_THREE_QUARTERS)


class TestMapTerrain(unittest.TestCase):

    def test_wall_blocks_los_and_movement(self):
        battle_map = BattleMap(6, 3)
        left = fighter('Лучник', 0, reach=60, speed=0)
        right = fighter('Цель', 1, speed=0)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 2, 0)
        battle_map.set_terrain(1, 0, 'wall')
        self.assertEqual(battle_map.combat_cover(left, right), COVER_TOTAL)
        self.assertFalse(battle_map.cell_free(1, 0, enemy=left))
        self.assertIsNone(battle_map.travel_cost(left, 1, 0))

    def test_empty_map_has_no_cover_even_with_a_creature_between(self):
        battle_map = BattleMap(6, 3)
        left = fighter('Лучник', 0, reach=60)
        mid = fighter('Щит', 0, speed=0)
        right = fighter('Цель', 1, speed=0)
        battle_map.place(left, 0, 0)
        battle_map.place(mid, 1, 0)
        battle_map.place(right, 2, 0)
        self.assertEqual(battle_map.combat_cover(left, right), COVER_NONE)
        self.assertEqual(
            battle_map.cover_between(left, right, creatures=True), COVER_HALF)

    def test_difficult_terrain_doubles_the_step(self):
        random.seed(1)
        battle_map = BattleMap(8, 2)
        seal_row(battle_map, 1, 8)
        left = fighter('Пеший', 0, speed=30)
        right = fighter('Цель', 1, speed=0)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 4, 0)
        battle_map.set_terrain(1, 0, 'difficult')
        battle_map.set_terrain(2, 0, 'water')
        battle_map.move_towards(left, right, 30, reach_ft=5)
        self.assertEqual(battle_map.get_pos(left), (3, 0))
        self.assertEqual(left.moved_ft, 25)
        self.assertEqual(battle_map.distance_ft(left, right), 5)

    def test_path_walks_around_a_wall(self):
        random.seed(2)
        battle_map = BattleMap(6, 3)
        left = fighter('Обход', 0, speed=30)
        right = fighter('Цель', 1, speed=0)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 2, 0)
        battle_map.set_terrain(1, 0, 'wall')
        battle_map.move_towards(left, right, 30, reach_ft=5)
        self.assertNotEqual(battle_map.terrain_at(*[int(v) for v in battle_map.get_pos(left)]),
                            'wall')
        self.assertEqual(battle_map.distance_ft(left, right), 5)
        self.assertNotEqual(battle_map.combat_cover(left, right), COVER_TOTAL)
        self.assertLessEqual(left.moved_ft, 30)

    def test_short_budget_cannot_cross_difficult_ground(self):
        battle_map = BattleMap(6, 2)
        seal_row(battle_map, 1, 6)
        left = fighter('Медленный', 0, speed=5)
        right = fighter('Цель', 1, speed=0)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 3, 0)
        battle_map.set_terrain(1, 0, 'difficult')
        battle_map.move_towards(left, right, 5, reach_ft=5)
        self.assertEqual(battle_map.get_pos(left), (0, 0))


class TestCombatUsesTerrain(unittest.TestCase):

    def test_attack_does_not_pass_a_wall(self):
        battle_map = BattleMap(6, 3)
        left = fighter('Лучник', 0, reach=60, speed=0, bonus=8)
        right = fighter('Цель', 1, speed=0, hp=30)
        left._rng = Roll(15, 4)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 2, 0)
        battle_map.set_terrain(1, 0, 'wall')
        lines, killed = execute_strikes(
            left, right, left.attacks, [[left], [right]], {}, battle_map)
        self.assertFalse(killed)
        self.assertEqual(right.hp, 30)
        self.assertIn('полное укрытие', lines[0])

    def test_half_cover_adds_two_to_ac(self):
        battle_map = BattleMap(6, 2)
        left = fighter('Лучник', 0, reach=60, speed=0, bonus=0)
        right = fighter('Цель', 1, speed=0, ac=10, hp=30)
        left._rng = Roll(10)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 3, 0)
        battle_map.set_terrain(3, 0, 'half')
        lines, _killed = execute_strikes(
            left, right, left.attacks, [[left], [right]], {}, battle_map)
        self.assertIn('(+2 укрытие)', lines[0])
        self.assertIn('ПРОМАХ', lines[0])
        self.assertEqual(right.hp, 30)

    def test_same_roll_hits_without_cover(self):
        battle_map = BattleMap(6, 2)
        left = fighter('Лучник', 0, reach=60, speed=0, bonus=0)
        right = fighter('Цель', 1, speed=0, ac=10, hp=30)
        left._rng = Roll(10, 3)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 3, 0)
        lines, _killed = execute_strikes(
            left, right, left.attacks, [[left], [right]], {}, battle_map)
        self.assertIn('ПОПАДАНИЕ', lines[0])
        self.assertNotIn('укрытие', lines[0])
        self.assertLess(right.hp, 30)

    def test_round_walks_around_wall_and_attacks(self):
        random.seed(4)
        battle_map = BattleMap(8, 4)
        left = fighter('Мечник', 0, speed=30, reach=5)
        right = fighter('Жертва', 1, speed=0, reach=5)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 2, 0)
        battle_map.set_terrain(1, 0, 'wall')
        _outcome, log = run_round(
            [[left], [right]], ['А', 'Б'], {}, battle_map, DecisionEngine(),
            auto_move=True, rng=random.Random(1))
        self.assertEqual(battle_map.distance_ft(left, right), 5)
        self.assertTrue('ПОПАДАНИЕ' in log or 'ПРОМАХ' in log)
        self.assertNotIn('полное укрытие', log)

    def test_area_does_not_pass_a_wall(self):
        battle_map = BattleMap(8, 3)
        left = fighter('Маг', 0, speed=0)
        right = fighter('Цель', 1, speed=0, hp=40)
        left._rng = Roll(6)
        right._rng = Roll(1)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 4, 0)
        effect = {
            'name': 'Волна', 'ability': 'dex', 'dc': 10,
            'damage': {'dice_count': 1, 'dice_type': 'd6', 'modifier': 0,
                       'damage_type': 'огонь'},
            'half_on_success': False, 'conditions': [],
            'area': 'radius', 'range_ft': 30,
        }
        open_events = execute_effect(
            left, effect, [[left], [right]], set(), battle_map)
        self.assertTrue(any(event.target == 'Цель' for event in open_events))
        right.hp = 40
        battle_map.set_terrain(2, 0, 'wall')
        blocked = execute_effect(
            left, effect, [[left], [right]], set(), battle_map)
        self.assertFalse(any(event.target == 'Цель' for event in blocked))
        self.assertEqual(right.hp, 40)

    def test_dex_save_gains_cover(self):
        battle_map = BattleMap(6, 2)
        left = fighter('Маг', 0, speed=0)
        right = fighter('Цель', 1, speed=0, hp=40)
        left._rng = Roll(4)
        right._rng = Roll(10)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 1, 0)
        battle_map.set_terrain(1, 0, 'three_quarters')
        effect = {
            'name': 'Искра', 'ability': 'dex', 'dc': 14,
            'damage': {'dice_count': 1, 'dice_type': 'd4', 'modifier': 0,
                       'damage_type': 'огонь'},
            'half_on_success': False, 'conditions': [],
            'area': 'single', 'range_ft': 30,
        }
        events = execute_effect(
            left, effect, [[left], [right]], set(), battle_map)
        text = ' '.join(event.text or '' for event in events)
        self.assertIn('укрытие +5', text)
        self.assertIn('успех', text)
        self.assertEqual(right.hp, 40)


class TestTerrainPersistence(unittest.TestCase):

    def _doc(self):
        left = fighter('Орк', 0)
        right = fighter('Эльф', 1)
        battle_map = BattleMap(8, 4)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 3, 0)

        class Doc:
            pass

        doc = Doc()
        doc.sides = [[left], [right]]
        doc.side_names = ['А', 'Б']
        doc.ignore_sides = {}
        doc.alliance_settings = []
        doc.battle_map = battle_map
        doc.battle_events = []
        doc.round_no = 0
        doc.engine = DecisionEngine()
        doc.setup = []
        doc.selected = left
        return doc

    def test_snapshot_roundtrip_and_undo(self):
        doc = self._doc()
        before = capture_battle(doc)
        self.assertNotIn('terrain', before['map'])
        doc.battle_map.set_terrain(1, 0, 'wall')
        doc.battle_map.set_terrain(2, 1, 'water')
        history = BattleHistory()
        history.commit('рельеф', before, capture_battle(doc))
        self.assertEqual(doc.battle_map.terrain_at(1, 0), 'wall')
        apply_snapshot(history.undo(), doc)
        self.assertIsNone(doc.battle_map.terrain_at(1, 0))
        self.assertFalse(doc.battle_map.has_terrain())
        apply_snapshot(history.redo(), doc)
        self.assertEqual(doc.battle_map.terrain_at(1, 0), 'wall')
        self.assertEqual(doc.battle_map.terrain_at(2, 1), 'water')
        blob = json.dumps(capture_battle(doc))
        other = self._doc()
        apply_snapshot(json.loads(blob), other)
        self.assertEqual(other.battle_map.terrain_records(),
                         doc.battle_map.terrain_records())

    def test_spawn_and_batch_keep_the_wall(self):
        left = fighter('Лучник', 0, reach=60, speed=0, hp=12, bonus=19)
        right = fighter('Цель', 1, speed=0, hp=12, ac=10)
        battle_map = BattleMap(6, 3)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 2, 0)
        battle_map.set_terrain(1, 0, 'wall')
        snap = snapshot_from_sides([[left], [right]], ['А', 'Б'], battle_map)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'scene.json')
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(snap, handle)
            loaded = load_snapshot(path)
        self.assertEqual(loaded['map']['terrain'], [[1, 0, 'wall']])
        _sides, _names, _ignore, spawned = spawn_scene(loaded, random.Random(1))
        self.assertEqual(spawned.terrain_at(1, 0), 'wall')
        blocked = run_one(loaded, seed=3, max_rounds=1)
        target = next(creature for creature in blocked.creatures
                      if creature.name == 'Цель')
        self.assertEqual(target.hp, 12)
        open_snap = snapshot_from_sides(
            [[left], [right]], ['А', 'Б'], BattleMap(6, 3))
        # Позиции в открытом снимке те же, стены нет: выстрел доходит.
        open_snap['map'] = {
            'width': 6, 'height': 3,
            'positions': snap['map']['positions'],
        }
        fired = run_one(open_snap, seed=3, max_rounds=1)
        wounded = next(creature for creature in fired.creatures
                       if creature.name == 'Цель')
        self.assertLess(wounded.hp, 12)


class TestTerrainEditor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_brush_stroke_undo_and_clear(self):
        win = MainWindow()
        try:
            left = fighter('Орк', 0)
            win.sides = [[left], []]
            win.side_names = ['А', 'Б']
            win.battle_map = BattleMap(8, 4)
            win.battle_map.place(left, 0, 0)
            win.history.clear()
            win._current = capture_battle(win)
            win._history_ready = True
            win._sync_history_actions()
            win.show()
            self._app.processEvents()
            win.set_terrain_mode(True)
            self._app.processEvents()
            self.assertTrue(win.terrain_bar.isVisible())
            self.assertTrue(win.terrain_btn.isChecked())
            self.assertTrue(win.act_terrain.isChecked())
            self.assertTrue(win.map_view._terrain_mode)
            win.set_terrain_brush('difficult')
            win.on_terrain_cell(2, 1, False)
            win.on_terrain_cell(3, 1, False)
            win.on_terrain_cell(3, 1, True)
            win.finish_terrain_stroke()
            self.assertEqual(win.battle_map.terrain_at(2, 1), 'difficult')
            self.assertIsNone(win.battle_map.terrain_at(3, 1))
            self.assertEqual(win.undo_action.text(), 'Отменить: рельеф')
            win.do_undo()
            self.assertFalse(win.battle_map.has_terrain())
            win.do_redo()
            self.assertEqual(win.battle_map.terrain_at(2, 1), 'difficult')
            win.clear_terrain()
            self.assertFalse(win.battle_map.has_terrain())
            win.do_undo()
            self.assertEqual(win.battle_map.terrain_at(2, 1), 'difficult')
        finally:
            win.close()
