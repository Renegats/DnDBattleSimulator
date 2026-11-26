"""Шаблоны областей, прицел ИИ, дружественный огонь и ручной выбор цели.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_aoe
"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from battle_map_model import (BattleMap, emanation_cells, footprint_cells,
                              template_cells)
from battle_round import ManualAction, run_round
from battle_strategies import AggressiveStrategy
from combat_log import CombatEvent
from decision_engine import DecisionEngine
from effects import (aim_at, best_placement, execute_effect, parse_area,
                     parse_special_effect)
from entities import Attack, Enemy
from monte_carlo import run_one, snapshot_from_sides
from tests.test_conditions import Scripted, unit


def _effect(**kwargs):
    base = {
        'name': 'Дыхание',
        'area': 'cone',
        'range_ft': 30,
        'width_ft': None,
        'height_ft': None,
        'placed': False,
        'place_ft': None,
        'ability': 'dex',
        'dc': 30,
        'half_on_success': True,
        'damage': {'dice_count': 1, 'dice_type': 'd4', 'modifier': 0,
                   'damage_type': 'огонь'},
        'conditions': [],
        'choice': False,
        'recharge': None,
    }
    base.update(kwargs)
    return base


def _placed(name, side, x, y, battle, *, hp=40, rng=None, size='Средний'):
    enemy = unit(name, side, hp=hp, rng=rng)
    enemy.size = size
    battle.place(enemy, x, y)
    return enemy


class TestTemplates(unittest.TestCase):

    def test_sphere_of_5_feet_covers_four_cells_around_the_intersection(self):
        cells = template_cells('sphere', (0, 0), None, 5)
        self.assertEqual(cells, {(-1, -1), (-1, 0), (0, -1), (0, 0)})

    def test_sphere_of_20_feet_is_a_circle_not_a_square(self):
        cells = template_cells('sphere', (0, 0), None, 20)
        self.assertIn((0, 0), cells)
        self.assertIn((3, 0), cells)
        self.assertNotIn((4, 0), cells)
        self.assertNotIn((3, 3), cells)
        self.assertEqual(len(cells), 52)
        self.assertEqual(template_cells('radius', (0, 0), None, 20), cells)

    def test_cylinder_on_a_flat_map_matches_the_circle_and_ignores_height(self):
        circle = template_cells('sphere', (2, 2), None, 10)
        cylinder = template_cells('cylinder', (2, 2), None, 10, height_ft=40)
        self.assertEqual(cylinder, circle)

    def test_cone_grows_with_distance_and_does_not_cover_behind(self):
        cells = template_cells('cone', (0, 0.5), (1, 0), 30)
        self.assertEqual(cells, {
            (0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0),
            (2, -1), (3, -1), (4, -1), (5, -1),
            (2, 1), (3, 1), (4, 1), (5, 1),
            (4, -2), (5, -2), (4, 2), (5, 2),
        })
        short = template_cells('cone', (0, 0.5), (1, 0), 15)
        self.assertNotIn((-1, 0), short)
        self.assertNotIn((0, 1), short)
        self.assertIn((2, 1), cells)
        self.assertEqual(short, {(0, 0), (1, 0), (2, 0), (2, -1), (2, 1)})

    def test_line_30_by_5_is_one_file_and_width_10_takes_the_half_cells(self):
        narrow = template_cells('line', (0, 0.5), (1, 0), 30, 5)
        self.assertEqual(narrow, {(x, 0) for x in range(6)})
        wide = template_cells('line', (0, 0.5), (1, 0), 30, 10)
        self.assertEqual(wide, {(x, y) for x in range(6) for y in (-1, 0, 1)})

    def test_diagonal_line_is_a_stair(self):
        cells = template_cells('line', (0, 0), (1, 1), 30, 5)
        self.assertGreaterEqual(len(cells), 3)
        self.assertTrue(all(x == y for x, y in cells))

    def test_cube_15_is_3x3_and_square_matches_it(self):
        cube = template_cells('cube', (0, 0), (1, 0), 15)
        self.assertEqual(cube, {(x, y) for x in range(3) for y in (-1, 0, 1)})
        self.assertEqual(template_cells('square', (0, 0), (1, 0), 15), cube)

    def test_cube_faces_north_from_the_near_edge(self):
        cells = template_cells('cube', (0, 0), (0, -1), 10)
        self.assertEqual(cells, {(-1, -1), (0, -1), (-1, -2), (0, -2)})

    def test_large_creature_is_hit_when_any_cell_overlaps(self):
        battle = BattleMap(12, 12)
        caster = _placed('Кастер', 0, 0, 0, battle)
        brute = _placed('Громада', 1, 3, 3, battle, size='Большой')
        self.assertEqual(footprint_cells(battle, brute), {(3, 3), (3, 4), (4, 3), (4, 4)})
        from effects import _occupants
        self.assertEqual(_occupants(caster, [[caster], [brute]], battle, {(4, 4)}), [brute])
        self.assertEqual(_occupants(caster, [[caster], [brute]], battle, {(6, 6)}), [])

    def test_emanation_of_5_feet_is_the_eight_neighbours(self):
        battle = BattleMap(8, 8)
        caster = _placed('Кастер', 0, 2, 2, battle)
        cells = emanation_cells(battle, caster, 5, bounds=(8, 8))
        self.assertNotIn((2, 2), cells)
        self.assertEqual(cells, {
            (1, 1), (2, 1), (3, 1),
            (1, 2), (3, 2),
            (1, 3), (2, 3), (3, 3),
        })


class TestParsing(unittest.TestCase):

    def test_russian_and_english_sizes(self):
        expectations = (
            ('60-футовый конус', 'cone', 60, None),
            ('линия длиной 30 фт и шириной 5 фт', 'line', 30, 5),
            ('в радиусе 20 фт', 'radius', 20, None),
            ('60-foot cone', 'cone', 60, None),
            ('line 30 feet long and 5 feet wide', 'line', 30, 5),
            ('within 20 feet', 'radius', 20, None),
            ('15-foot cube', 'cube', 15, None),
            ('куб со стороной 15 футов', 'cube', 15, None),
            ('10-foot square', 'square', 10, None),
        )
        for text, shape, size, width in expectations:
            spec, warning = parse_area(text)
            self.assertIsNone(warning, text)
            self.assertEqual(spec['shape'], shape, text)
            self.assertEqual(spec['size'], size, text)
            self.assertEqual(spec['width'], width, text)

    def test_cylinder_keeps_height_and_a_placed_center(self):
        spec, warning = parse_area(
            'Магма из точки в пределах 120 футов: гейзер 20 футов высотой и 5 футов радиусом.')
        self.assertIsNone(warning)
        self.assertEqual(spec['shape'], 'cylinder')
        self.assertEqual(spec['size'], 5)
        self.assertEqual(spec['height'], 20)
        self.assertTrue(spec['placed'])
        self.assertEqual(spec['place_ft'], 120)
        english, _warn = parse_area('20-foot radius sphere centered on a point within 120 feet')
        self.assertEqual(english['shape'], 'sphere')
        self.assertEqual(english['size'], 20)
        self.assertTrue(english['placed'])
        self.assertEqual(english['place_ft'], 120)

    def test_shape_without_a_size_stays_text(self):
        spec, warning = parse_area('Выдыхает странный конус.')
        self.assertIsNone(spec)
        self.assertIn('остаётся текстом', warning)
        effect, warning = parse_special_effect(
            'Странный конус',
            'Выдыхает странный конус. Существа совершают спасбросок Ловкости Сл 15, '
            'получая урон огнём 10 (3к6) при провале.')
        self.assertIsNone(effect)
        self.assertIn('остаётся текстом', warning)

    def test_ancient_cone_phrase_still_parses_inside_a_save(self):
        effect, warning = parse_special_effect(
            'Огненное дыхание',
            'Дракон выдыхает огонь 90-футовым конусом. Все существа в этой области '
            'должны совершить спасбросок Ловкости Сл 24, получая урон огнём 91 (26к6) '
            'при провале, или половину этого урона при успехе.')
        self.assertIsNone(warning)
        self.assertEqual(effect['area'], 'cone')
        self.assertEqual(effect['range_ft'], 90)
        self.assertFalse(effect['placed'])


class TestAimAndFriendlyFire(unittest.TestCase):

    def _lane(self):
        battle = BattleMap(16, 16)
        dragon = _placed('Дракон', 0, 5, 5, battle, hp=90, rng=Scripted([4]))
        ally = _placed('Союзник', 0, 8, 5, battle, hp=40, rng=Scripted([1]))
        east = [
            _placed('Орк', 1, 9, 5, battle, hp=40, rng=Scripted([1])),
            _placed('Гоблин', 1, 10, 5, battle, hp=40, rng=Scripted([1])),
        ]
        north = _placed('Север', 1, 5, 2, battle, hp=40, rng=Scripted([1]))
        sides = [[dragon, ally], east + [north]]
        return battle, dragon, ally, east, north, sides

    def test_ai_turns_the_cone_away_from_the_ally(self):
        battle, dragon, ally, east, north, sides = self._lane()
        placement = best_placement(dragon, _effect(), sides, set(), battle)
        self.assertIsNotNone(placement)
        self.assertIn('север', placement.label)
        self.assertIn(north, placement.creatures)
        self.assertNotIn(ally, placement.creatures)
        for enemy in east:
            self.assertNotIn(enemy, placement.creatures)
        before = {ally: ally.hp, north: north.hp}
        events = execute_effect(dragon, _effect(), sides, set(), battle)
        self.assertLess(north.hp, before[north])
        self.assertEqual(ally.hp, before[ally])
        header = next(event for event in events if event.result == 'area')
        self.assertIn('Север', header.text)
        self.assertNotIn('Союзник', header.text)
        self.assertNotIn('упрощ', header.text or '')
        self.assertTrue(header.area_cells)
        self.assertIn(id(north), header.area_ids)

    def test_friendly_fire_lands_when_the_enemies_are_worth_it(self):
        battle = BattleMap(16, 16)
        dragon = _placed('Дракон', 0, 5, 5, battle, hp=90, rng=Scripted([4]))
        ally = _placed('Союзник', 0, 7, 5, battle, hp=40, rng=Scripted([1]))
        foes = [
            _placed(name, 1, x, 5, battle, hp=40, rng=Scripted([1]))
            for name, x in (('А', 8), ('Б', 9), ('В', 10))
        ]
        sides = [[dragon, ally], foes]
        events = execute_effect(dragon, _effect(), sides, set(), battle)
        self.assertLess(ally.hp, 40)
        for enemy in foes:
            self.assertLess(enemy.hp, 40)
        header = next(event for event in events if event.result == 'area')
        self.assertIn('Союзник', header.text)
        self.assertIn('А', header.text)

    def test_choice_keeps_allies_out_of_the_same_cone(self):
        battle, dragon, ally, east, _north, sides = self._lane()
        effect = _effect(choice=True)
        aimed = aim_at(dragon, effect, battle, (10, 5), sides, set())
        self.assertIn(ally, aimed.creatures)
        events = execute_effect(
            dragon, effect, sides, set(), battle, placement=aimed,
            include=[creature for creature in aimed.creatures if creature.side != 0])
        self.assertEqual(ally.hp, 40)
        self.assertTrue(any(event.target == 'Орк' for event in events))


class TestManualAndBatch(unittest.TestCase):

    def test_manual_attack_ignores_the_ai_target(self):
        def scene():
            hero = unit('Герой', 0, hp=30, rng=Scripted([15, 15, 18, 4]), attacks=[
                Attack('Меч', 8, 1, 'd6', 2, 'рубящий')])
            hero.strategy = AggressiveStrategy()
            weak = unit('Слабый', 1, hp=8, rng=Scripted([1, 1, 1, 1]))
            tough = unit('Крепкий', 1, hp=40, rng=Scripted([1, 1, 1, 1]))
            weak.strategy = AggressiveStrategy()
            tough.strategy = AggressiveStrategy()
            battle = BattleMap(10, 8)
            battle.place(hero, 1, 1)
            battle.place(weak, 2, 1)
            battle.place(tough, 1, 2)
            return hero, weak, tough, battle

        def played(controller=None):
            hero, weak, tough, battle = scene()
            result = run_round(
                [[hero], [weak, tough]], ['А', 'Б'], {}, battle, DecisionEngine(),
                auto_move=False, controller=controller)
            hits = [event.target for event in result.events
                    if event.kind == 'attack' and event.actor == 'Герой' and event.result == 'hit']
            return hits, weak.hp, tough.hp

        auto_hits, weak_hp, tough_hp = played()
        self.assertEqual(auto_hits, ['Слабый'])
        self.assertLess(weak_hp, 8)
        self.assertEqual(tough_hp, 40)

        hero, weak, tough, battle = scene()

        def bound(attacker, side):
            if attacker.name != 'Герой':
                return None
            return ManualAction('attack', attack=attacker.attacks[0], target=tough)

        result = run_round(
            [[hero], [weak, tough]], ['А', 'Б'], {}, battle, DecisionEngine(),
            auto_move=False, controller=bound)
        hits = [event.target for event in result.events
                if event.kind == 'attack' and event.actor == 'Герой']
        self.assertEqual(hits, ['Крепкий'])
        self.assertEqual(weak.hp, 8)
        self.assertLess(tough.hp, 40)
        self.assertTrue(any('ручная атака' in (event.text or '') for event in result.events))

    def test_manual_cone_uses_the_given_direction(self):
        battle = BattleMap(16, 16)
        dragon = _placed('Дракон', 0, 5, 5, battle, hp=90, rng=Scripted([15, 15, 4]))
        dragon.special_actions = [{'name': 'Дыхание', 'effect': _effect(name='Дыхание')}]
        ally = _placed('Союзник', 0, 8, 5, battle, hp=40, rng=Scripted([2, 2]))
        from conditions import apply_condition
        apply_condition(ally, 'stunned')
        north = _placed('Север', 1, 5, 2, battle, hp=40, rng=Scripted([1, 1, 1, 1]))
        north.strategy = AggressiveStrategy()
        dragon.strategy = AggressiveStrategy()
        sides = [[dragon, ally], [north]]
        effect = dragon.special_actions[0]['effect']
        safe = best_placement(dragon, effect, sides, set(), battle)
        self.assertIn('север', safe.label)
        forced = aim_at(dragon, effect, battle, (10, 5), sides, set())
        self.assertIn(ally, forced.creatures)
        self.assertNotIn(north, forced.creatures)

        def controller(attacker, _side):
            if attacker is not dragon:
                return None
            return ManualAction('effect', effect=effect, placement=forced)

        result = run_round(
            sides, ['Драконы', 'Север'], {}, battle, DecisionEngine(),
            auto_move=False, controller=controller)
        self.assertLess(ally.hp, 40)
        self.assertEqual(north.hp, 40)
        self.assertTrue(any(event.result == 'area' and 'Союзник' in (event.text or '')
                            for event in result.events))

    def test_area_event_roundtrip(self):
        event = CombatEvent(
            kind='save', result='area', text='конус 30 фт: Север',
            area_cells=[(1, 2), (3, 4)], area_origin=(0.5, 1), area_ids=[7])
        again = CombatEvent.from_dict(event.to_dict())
        self.assertEqual(again.area_cells, [(1, 2), (3, 4)])
        self.assertEqual(again.area_origin, (0.5, 1))
        self.assertEqual(again.area_ids, [7])

    def test_batch_runs_a_cone_without_ui(self):
        dragon = Enemy('Дракон', 90, 18, [Attack('Укус', 5, 1, 'd4', 1, 'колющий')], 0, speed=30)
        dragon.size = 'Средний'
        dragon.ability_mods = {'dex': 0}
        dragon.special_actions = [{'name': 'Дыхание', 'effect': _effect(
            range_ft=30, damage={'dice_count': 1, 'dice_type': 'd4', 'modifier': 20,
                                 'damage_type': 'огонь'})}]
        victim = Enemy('Жертва', 80, 12, [Attack('Кинжал', 2, 1, 'd4', 0, 'колющий')], 1, speed=30)
        victim.size = 'Средний'
        victim.ability_mods = {'dex': 0}
        battle = BattleMap(12, 8)
        battle.place(dragon, 0, 0)
        battle.place(victim, 1, 0)
        snapshot = snapshot_from_sides([[dragon], [victim]], ['Дракон', 'Жертва'], battle)
        row = run_one(snapshot, seed=3, max_rounds=1)
        self.assertEqual(row.rounds, 1)
        wounded = next(creature for creature in row.creatures if creature.name == 'Жертва')
        self.assertLess(wounded.hp, 80)


class TestQtPreview(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def test_preview_and_resolved_cells_are_painted(self):
        from qt_app import MainWindow
        window = MainWindow()
        battle = BattleMap(16, 16)
        dragon = _placed('Дракон', 0, 5, 5, battle, hp=90)
        north = _placed('Север', 1, 5, 2, battle)
        window.sides = [[dragon], [north]]
        window.side_names = ['Драконы', 'Север']
        window.battle_map = battle
        window.selected = dragon
        window.ignore_sides = {}
        window.map_view.rebuild(battle, window.sides, dragon)
        self.assertTrue(window.manual_toggle.objectName())
        self.assertFalse(window.manual_bar.isVisible())
        effect = _effect()
        window._manual_actor = dragon
        window._manual_effect = effect
        window._manual_kind = 'effect'
        window._manual_include = None
        window._manual_aim((5, 1))
        self.assertTrue(window.map_view._preview_cells)
        self.assertIn('Север', window.manual_hit.text())
        window.map_view.set_area_cells(window.map_view._preview_cells)
        window.map_view.set_preview_cells([])
        self.assertGreaterEqual(len(window.map_view._area_items), len(window.map_view._area_cells))
        window.close()
