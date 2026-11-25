"""Юнит-тесты магичности оружия: условные иммунитеты «от немагического оружия».

Покрывают всю цепочку: Attack.magical -> сериализация -> modify_damage ->
execute_strikes -> DecisionEngine (A5/B2). Без tkinter и без реальных бросков.
"""
import unittest
from types import SimpleNamespace

from entities import Attack, Enemy
from combat_core import modify_damage, execute_strikes
from decision_engine import (DecisionEngine, immunity_blocks, is_nonmagical_only,
                             active_defenses)
from battle_strategies import AggressiveStrategy

COND = 'дробящий от немагического оружия'


class FakeTarget:
    def __init__(self, hp=50, ac=18, immunities=(), resistances=(), side=1):
        self.name = 'Демон'
        self.hp = self.max_hp = hp
        self.ac = ac
        self.alive = True
        self.immunities = list(immunities)
        self.resistances = list(resistances)
        self.vulnerabilities = []
        self.side = side
        self.pos = (1, 0)
        self.attacks = []
        self.ignore_sides = set()

    def take_damage(self, dmg):
        self.hp -= dmg
        if self.hp <= 0:
            self.hp, self.alive = 0, False


def mock_attacker(result):
    a = SimpleNamespace(name='Рыцарь', side=0, alive=True, pos=(0, 0), ac=16,
                        hp=20, max_hp=20, attacks=[], ignore_sides=set(),
                        multiattack=None, speed=30, moved_ft=0,
                        ability_scores={'int': 10})
    a.perform_attack = lambda atk, ac, crit_mode='double_all', **_extra: result
    return a


def make_unit(name, side, attacks, *, int_score=10, pos=(0, 0), immunities=()):
    e = SimpleNamespace(name=name, side=side, alive=True, hp=30, max_hp=30, ac=15,
                        attacks=attacks, ability_scores={'int': int_score},
                        immunities=list(immunities), resistances=[], vulnerabilities=[],
                        multiattack=None, speed=30, pos=pos, ignore_sides=set(), moved_ft=0)
    e.strategy = AggressiveStrategy()
    return e


class TestMagicalWeapons(unittest.TestCase):

    # ---------- семантика записи защиты ----------
    def test_conditional_marker_detected(self):
        self.assertTrue(is_nonmagical_only(COND))
        self.assertTrue(is_nonmagical_only('bludgeoning from nonmagical attacks'))
        self.assertFalse(is_nonmagical_only('яд'))

    def test_blocks_matrix(self):
        self.assertTrue(immunity_blocks(COND, False))
        self.assertFalse(immunity_blocks(COND, True))
        self.assertTrue(immunity_blocks('яд', True))
        self.assertEqual(active_defenses([COND, 'яд'], True), {'poison'})

    # ---------- расчёт урона ----------
    def test_nonmagical_blocked_by_conditional_immunity(self):
        t = FakeTarget(immunities=[COND])
        final, note = modify_damage(t, 12, 'дробящий', magical=False)
        self.assertEqual(final, 0)
        self.assertIn('иммунитет', note)
        self.assertEqual(t.hp, 50)

    def test_magical_pierces_conditional_immunity(self):
        t = FakeTarget(immunities=[COND])
        final, note = modify_damage(t, 12, 'дробящий', magical=True)
        self.assertEqual(final, 12)
        self.assertIn('пробило иммунитет', note)

    def test_magical_does_not_pierce_unconditional_immunity(self):
        t = FakeTarget(immunities=['яд'])
        final, _ = modify_damage(t, 12, 'яд', magical=True)
        self.assertEqual(final, 0)

    def test_magical_pierces_conditional_resistance(self):
        t = FakeTarget(resistances=[COND])
        self.assertEqual(modify_damage(t, 12, 'дробящий', magical=False)[0], 6)
        self.assertEqual(modify_damage(t, 12, 'дробящий', magical=True)[0], 12)

    # ---------- сквозной удар ----------
    def test_execute_strikes_magical_kills_what_nonmagical_cannot(self):
        atk_plain = SimpleNamespace(name='Дубина', attack_bonus=5, damage_dice_count=1,
                                    damage_dice_type='d8', damage_modifier=2,
                                    damage_type='дробящий', range_ft=5, magical=False)
        atk_magic = SimpleNamespace(name='Дубина +1', attack_bonus=6, damage_dice_count=1,
                                    damage_dice_type='d8', damage_modifier=3,
                                    damage_type='дробящий', range_ft=5, magical=True)
        roll = (True, 10, 20, False, '10 урона (дробящий)')

        t1 = FakeTarget(hp=10, immunities=[COND])
        a1 = mock_attacker(roll)
        execute_strikes(a1, t1, [atk_plain], [[a1], [t1]], {}, None)
        self.assertEqual(t1.hp, 10)
        self.assertTrue(t1.alive)

        t2 = FakeTarget(hp=10, immunities=[COND])
        a2 = mock_attacker(roll)
        lines, killed = execute_strikes(a2, t2, [atk_magic], [[a2], [t2]], {}, None)
        self.assertEqual(t2.hp, 0)
        self.assertFalse(t2.alive)
        self.assertTrue(killed)
        self.assertIn('УНИЧТОЖЕН', '\n'.join(lines))

    # ---------- мозг ----------
    def test_engine_all_immune_depends_on_magical(self):
        eng = DecisionEngine()
        plain = Attack('Дубина', 5, 1, 'd8', 2, 'дробящий', 5, False)
        magic = Attack('Дубина +1', 6, 1, 'd8', 3, 'дробящий', 5, True)
        demon = make_unit('Демон', 1, [Attack('Коготь', 8, 2, 'd6', 4, 'рубящий')],
                          pos=(1, 0), immunities=[COND])
        weak = make_unit('Рыцарь', 0, [plain], pos=(0, 0))
        self.assertTrue(eng._all_immune(weak, demon))
        strong = make_unit('Паладин', 0, [magic], pos=(0, 0))
        self.assertFalse(eng._all_immune(strong, demon))

    def test_engine_prefers_magical_weapon_in_pool(self):
        eng = DecisionEngine()
        plain = Attack('Дубина', 5, 1, 'd8', 2, 'дробящий', 5, False)
        magic = Attack('Дубина +1', 6, 1, 'd8', 3, 'дробящий', 5, True)
        demon = make_unit('Демон', 1, [Attack('Коготь', 8, 2, 'd6', 4, 'рубящий')],
                          pos=(1, 0), immunities=[COND])
        hero = make_unit('Паладин', 0, [plain, magic], pos=(0, 0), int_score=12)
        decision = eng.decide(hero, [[hero], [demon]], set())
        self.assertEqual(decision.attack.name, 'Дубина +1')
        snap = eng.get_round_log()[-1]
        cand = {c['name']: c for c in snap['candidates']}
        self.assertEqual(cand['Дубина']['eff'], 0.0)
        self.assertEqual(cand['Дубина +1']['eff'], 1.0)
        self.assertTrue(cand['Дубина +1']['chosen'])

    # ---------- сериализация ----------
    def test_attack_roundtrip_preserves_magical(self):
        a = Attack('Меч +2', 8, 1, 'd8', 4, 'рубящий', 5, True)
        b = Attack.from_dict(a.to_dict())
        self.assertTrue(b.magical)
        self.assertEqual(b.name, a.name)
        self.assertEqual(b.range_ft, a.range_ft)
        self.assertFalse(Attack.from_dict({'name': 'x', 'attack_bonus': 0,
                                           'damage_dice_count': 1,
                                           'damage_dice_type': 'd6',
                                           'damage_modifier': 0}).magical)

    def test_enemy_roundtrip_preserves_magical(self):
        e = Enemy('Паладин', 30, 18, [Attack('Меч +2', 8, 1, 'd8', 4, 'рубящий', 5, True)], 0)
        restored = Enemy.from_dict(e.to_dict())
        self.assertTrue(restored.attacks[0].magical)


if __name__ == '__main__':
    unittest.main(verbosity=2)