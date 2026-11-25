"""Юнит-тесты слоя бросков (entities.Enemy.perform_attack) через DI rng.

Внедрение НОВОЙ зависимости (в отличие от шага 1, где переносили существующую
ENGINE): генерация случайных чисел вынесена за границу слоя как контракт
randint() и внедряется через конструктор Enemy(rng=...). Продакшн-путь
rng=None => модульный random (нулевая регрессия, проверено
test_default_rng_is_module_random); тестовый => скриптованный stub / seeded fake.

Два вида test double осознанно:
  * ScriptedRng = Mock/Stub (подмена ПОВЕДЕНИЯ): точные числа => проверяем
    логику крита/промаха/клампинга конкретными assert'ами;
  * random.Random(seed) = seeded Fake (подмена ДАННЫХ последовательности):
    проверяем воспроизводимость и целость продакшн-дефолта.

Честная пометка про seed: random.Random(7) НЕ совпадает с global random.seed(7) -
независимые генераторы. Тесту важна детерминированность внутри себя, а не
репликация рандомного прогона; бой остаётся стохастическим (rng=None -> random).
"""
import random
import unittest

from entities import Attack, Enemy


class ScriptedRng:
    """Stub-rng: выдаёт заранее заданную последовательность через контракт
    randint(a,b). Лишний бросок => AssertionError (активная проверка, что при
    промахе цикл урона не запускается)."""
    def __init__(self, rolls):
        self._rolls = list(rolls)
        self._i = 0

    def randint(self, a, b):
        if self._i >= len(self._rolls):
            raise AssertionError(
                f"rng вызван {self._i + 1}-й раз, но скрипт задан на {len(self._rolls)}")
        v = self._rolls[self._i]
        self._i += 1
        return v


def club(*, bonus=0, count=1, dice='d6', mod=2, dtype='рубящий'):
    return Attack('Дубина', bonus, count, dice, mod, dtype)


def make_enemy(rng, *, hp=10, ac=15, attack=None):
    return Enemy('Гоблин', hp, ac, [attack or club()], side=0, rng=rng)


class TestPerformAttack(unittest.TestCase):

    def test_critical_doubles_damage_and_ignores_ac(self):
        # ac=99 недостижим, но crit (d20=20) обязан попасть, игнорируя AC; d6=5 -> 5+2=7 -> *2=14
        e = make_enemy(ScriptedRng([20, 5]), attack=club(mod=2))
        hit, damage, total, critical, info = e.perform_attack(club(mod=2), 99)
        self.assertTrue(hit, 'крит попадает, игнорируя AC')
        self.assertTrue(critical)
        self.assertEqual(total, 20)
        self.assertEqual(damage, 14, 'крит удваивает урон: (5+2)*2')
        self.assertIn('14 урона', info)

    def test_hit_without_critical(self):
        e = make_enemy(ScriptedRng([10, 4]), attack=club(bonus=5))
        hit, damage, total, critical, info = e.perform_attack(club(bonus=5), 10)
        self.assertTrue(hit)
        self.assertFalse(critical)
        self.assertEqual(total, 15)
        self.assertEqual(damage, 6, 'не крит => урон не удваивается')

    def test_miss_does_not_roll_damage_dice(self):
        # Скрипт [1] намеренно КОРОЧЕ: лишний бросок кости уронa при промахе
        # бросил бы AssertionError => доказываем отсутствие лишних бросков.
        e = make_enemy(ScriptedRng([1]), attack=club(bonus=0))
        hit, damage, total, critical, info = e.perform_attack(club(bonus=0), 25)
        self.assertFalse(hit)
        self.assertEqual(damage, 0, 'промах => нулевой урон')
        self.assertEqual(total, 1)
        self.assertFalse(critical)
        self.assertEqual(info, '')

    def test_negative_damage_clamped_to_zero(self):
        e = make_enemy(ScriptedRng([1, 1]), attack=club(bonus=5, mod=-10))
        hit, damage, total, critical, info = e.perform_attack(club(bonus=5, mod=-10), 1)
        self.assertTrue(hit)
        self.assertEqual(damage, 0, 'damage=max(0, raw) защищает от отрицательного урона')
        self.assertIn('0 урона', info)

    def test_seeded_rng_is_reproducible(self):
        atk = club(bonus=3, count=2, mod=1)
        e1 = make_enemy(random.Random(7), attack=atk)
        e2 = make_enemy(random.Random(7), attack=atk)
        self.assertEqual(e1.perform_attack(atk, 12), e2.perform_attack(atk, 12),
                         'одинаковое зерно => идентичный кортеж результата')

    def test_default_rng_is_module_random(self):
        e = Enemy('Гоблин', 10, 15, [club()], side=0)   # rng не передаём
        self.assertIs(e._rng, random, 'дефолт => модульный random (prod-путь цел)')
        res = e.perform_attack(club(), 10)
        self.assertEqual(len(res), 5)
        self.assertIsInstance(res[0], bool)
        self.assertIsInstance(res[1], int)
        self.assertIsInstance(res[2], int)
        self.assertIsInstance(res[3], bool)
        self.assertIsInstance(res[4], str)


if __name__ == '__main__':
    unittest.main(verbosity=2)