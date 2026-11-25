"""Юнит-тесты чистого слоя урона (combat_core.execute_strikes + modify_damage).

Плод фронта Р (симметрия 2б): слой урона уехал из battle_logic.py (оркестратор,
legitimately тянет tkinter для I/O: messagebox + вставка в tk.Text) в
combat_core.py (без tkinter). Поэтому этот тест импортирует combat_core
НАПРЯМУЮ, и в его графе импортов НЕТ tkinter вообще.

DI на уровне функций: execute_strikes больше не читает self.sides/
self.ignore_sides/self.battle_map миксина BattleSimulator - все внешние данные
передаются явными аргументами. Тест подставляет sides/ignore_sides/battle_map
явно и проверяет чистый расчёт без какого-либо GUI-контекста.

Вид test double = Mock на границе (perform_attack - заглушка, фиксированный
5-кортеж): слой урона изолирован от слоя бросков контрактом. Дополняет Т2-А
(там броски тестировались через DI rng).
"""
import unittest
from types import SimpleNamespace

from combat_core import execute_strikes, modify_damage


class FakeTarget:
    def __init__(self, name, hp, ac, immunities=(), resistances=(),
                 vulnerabilities=(), side=1):
        self.name, self.max_hp, self.hp, self.ac = name, hp, hp, ac
        self.alive = True
        self.immunities = list(immunities)
        self.resistances = list(resistances)
        self.vulnerabilities = list(vulnerabilities)
        self.side, self.pos, self.attacks = side, (0, 0), []
        self.ignore_sides = set()

    def take_damage(self, dmg):
        self.hp -= dmg
        if self.hp <= 0:
            self.hp, self.alive = 0, False


def club_attack():
    return SimpleNamespace(name='Дубина', attack_bonus=4, damage_dice_count=1,
                           damage_dice_type='d8', damage_modifier=2,
                           damage_type='дробящий', range_ft=5)


def mock_attacker(roll_result):
    a = SimpleNamespace(name='Гоблин', side=0, alive=True, pos=(0, 0), ac=15,
                        hp=7, max_hp=7, attacks=[], ignore_sides=set(),
                        multiattack=None, speed=30, moved_ft=0,
                        ability_scores={'int': 10})
    a.perform_attack = lambda atk, ac, crit_mode='double_all': roll_result
    return a


class TestDamageLayer(unittest.TestCase):

    def _run(self, target, roll_result):
        attacker = mock_attacker(roll_result)
        lines, killed = execute_strikes(
            attacker, target, [club_attack()],
            sides=[[attacker], [target]], ignore_sides={}, battle_map=None)
        return '\n'.join(lines), killed

    def test_immunity_zeroes_damage(self):
        demon = FakeTarget('Демон', hp=50, ac=18, immunities=['дробящий'])
        joined, killed = self._run(demon, (True, 10, 20, False, '10 урона (дробящий)'))
        self.assertEqual(demon.hp, 50)
        self.assertTrue(demon.alive)
        self.assertFalse(killed)
        self.assertIn('иммунитет: дробящий', joined)

    def test_critical_does_not_pierce_immunity(self):
        demon = FakeTarget('Демон', hp=50, ac=18, immunities=['дробящий'])
        joined, killed = self._run(demon, (True, 20, 20, True, '20 урона (дробящий)'))
        self.assertEqual(demon.hp, 50, 'крит не пробивает иммунитет')
        self.assertIn('КРИТИЧЕСКИЙ УДАР', joined)
        self.assertIn('иммунитет: дробящий', joined)
        self.assertFalse(killed)

    def test_resistance_halves_damage(self):
        t = FakeTarget('Термостойкий', hp=50, ac=15, resistances=['дробящий'])
        joined, _ = self._run(t, (True, 10, 20, False, '10 урона (дробящий)'))
        self.assertEqual(t.hp, 45)
        self.assertIn('сопротивление: дробящий', joined)

    def test_vulnerability_doubles_damage(self):
        t = FakeTarget('Хрупкий', hp=50, ac=15, vulnerabilities=['дробящий'])
        joined, _ = self._run(t, (True, 10, 20, False, '10 урона (дробящий)'))
        self.assertEqual(t.hp, 30)
        self.assertIn('уязвимость: дробящий', joined)

    def test_normal_target_takes_raw_damage(self):
        t = FakeTarget('Обычный', hp=50, ac=15)
        joined, _ = self._run(t, (True, 10, 20, False, '10 урона (дробящий)'))
        self.assertEqual(t.hp, 40)
        for word in ('иммунитет', 'сопротивление', 'уязвимость'):
            self.assertNotIn(word, joined)

    def test_miss_deals_no_damage(self):
        t = FakeTarget('Обычный', hp=50, ac=22)
        joined, killed = self._run(t, (False, 0, 5, False, ''))
        self.assertEqual(t.hp, 50)
        self.assertTrue(t.alive)
        self.assertFalse(killed)
        self.assertIn('ПРОМАХ', joined)

    def test_lethal_damage_kills_target(self):
        t = FakeTarget('Слабак', hp=5, ac=10)
        joined, killed = self._run(t, (True, 10, 20, False, '10 урона (дробящий)'))
        self.assertEqual(t.hp, 0)
        self.assertFalse(t.alive)
        self.assertTrue(killed)
        self.assertIn('УНИЧТОЖЕН', joined)

    def test_modify_damage_is_pure_function(self):
        t = FakeTarget('Демон', hp=50, ac=18, immunities=['дробящий'])
        final, note = modify_damage(t, 10, 'дробящий')
        self.assertEqual(final, 0)
        self.assertIn('иммунитет', note)
        self.assertEqual(t.hp, 50, 'modify_damage только считает, не наносит (hp трогает take_damage)')


if __name__ == '__main__':
    unittest.main(verbosity=2)