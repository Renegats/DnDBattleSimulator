"""Дистанция мили на карте: юнит должен подходить вплотную и бить.

Раньше find_path считал «в досягаемости» зазор в полуклетках <= reach*2,
а distance_ft = (gap + 2) * 2.5, поэтому мили останавливались в 10 фт
и лог писал «не может достать (10.0 фт > 5 фт)».
"""
import random
import unittest

from battle_map_model import BattleMap
from battle_round import run_round
from battle_strategies import AggressiveStrategy
from decision_engine import DecisionEngine
from entities import Attack, Enemy


def sword(name='Меч'):
    return Attack(name, 6, 1, 'd6', 2, 'рубящий', range_ft=5)


def fighter(name, side, *, size='Средний', speed=30, hp=30, reach=5):
    attacks = [sword()]
    attacks[0].range_ft = reach
    unit = Enemy(name, hp, 16, attacks, side, speed=speed, rng=random.Random(1))
    unit.size = size
    unit.strategy = AggressiveStrategy()
    unit.ability_scores = {'dex': 12, 'int': 10}
    unit.ability_mods = {'dex': 1, 'int': 0}
    return unit


class TestMeleeReach(unittest.TestCase):

    def test_medium_thirty_feet_apart_closes_to_five_and_attacks(self):
        random.seed(1)
        battle_map = BattleMap(20, 10)
        left = fighter('Мечник А', 0)
        right = fighter('Мечник Б', 1)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 6, 0)
        self.assertEqual(battle_map.distance_ft(left, right), 30.0)

        _outcome, log = run_round(
            [[left], [right]], ['А', 'Б'], {}, battle_map, DecisionEngine(),
            auto_move=True, rng=random.Random(2))

        self.assertEqual(battle_map.distance_ft(left, right), 5.0)
        self.assertNotIn('не может достать', log)
        self.assertTrue('ПОПАДАНИЕ' in log or 'ПРОМАХ' in log)
        self.assertIn('Мечник А', log)
        self.assertIn('Мечник Б', log)

    def test_medium_ten_feet_apart_steps_in_and_attacks(self):
        random.seed(3)
        battle_map = BattleMap(12, 8)
        left = fighter('А', 0)
        right = fighter('Б', 1)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 2, 0)
        self.assertEqual(battle_map.distance_ft(left, right), 10.0)

        _outcome, log = run_round(
            [[left], [right]], ['А', 'Б'], {}, battle_map, DecisionEngine(),
            auto_move=True, rng=random.Random(4))

        self.assertEqual(battle_map.distance_ft(left, right), 5.0)
        self.assertNotIn('не может достать', log)
        self.assertTrue('ПОПАДАНИЕ' in log or 'ПРОМАХ' in log)

    def test_large_and_huge_stop_adjacent_not_one_cell_short(self):
        random.seed(5)
        for size, cells_apart in (('Большой', 7), ('Огромный', 8)):
            battle_map = BattleMap(24, 12)
            left = fighter('Левый', 0, size=size, speed=30)
            right = fighter('Правый', 1, size=size, speed=0)
            battle_map.place(left, 0, 0)
            battle_map.place(right, cells_apart, 0)
            self.assertEqual(battle_map.distance_ft(left, right), 30.0, size)
            battle_map.move_towards(left, right, 30, reach_ft=5)
            self.assertEqual(battle_map.distance_ft(left, right), 5.0, size)
            self.assertFalse(self._halves(battle_map, left) & self._halves(battle_map, right),
                             size)

    def test_reach_weapon_stops_at_ten_feet(self):
        random.seed(6)
        battle_map = BattleMap(20, 8)
        left = fighter('Копейщик', 0, reach=10)
        right = fighter('Цель', 1, speed=0)
        battle_map.place(left, 0, 0)
        battle_map.place(right, 6, 0)
        self.assertEqual(battle_map.distance_ft(left, right), 30.0)
        battle_map.move_towards(left, right, 30, reach_ft=10)
        self.assertEqual(battle_map.distance_ft(left, right), 10.0)

    def test_cell_free_uses_large_footprint(self):
        battle_map = BattleMap(10, 10)
        big = fighter('Огр', 0, size='Большой')
        other = fighter('Гоблин', 1, size='Средний')
        battle_map.place(big, 0, 0)
        battle_map.place(other, 2, 0)
        # Якорь (1, 0) для среднего свободен (своя клетка игнорируется),
        # но пятно большого 2×2 накрывает гоблина.
        self.assertTrue(battle_map.cell_free(1, 0, ignore_id=id(big)))
        self.assertFalse(battle_map.cell_free(1, 0, ignore_id=id(big), enemy=big))

    @staticmethod
    def _halves(battle_map, enemy):
        pos = battle_map.get_pos(enemy)
        span = battle_map.span_of(enemy)
        hx, hy = int(round(pos[0] * 2)), int(round(pos[1] * 2))
        return {(x, y) for x in range(hx, hx + span) for y in range(hy, hy + span)}


if __name__ == '__main__':
    unittest.main(verbosity=2)
