"""Инициатива 5e, лечение и режим крита в run_round."""
import random
import unittest

from battle_round import living_initiative, run_round
from battle_strategies import AggressiveStrategy, SupportStrategy
from combat_core import execute_strikes
from decision_engine import DecisionEngine
from entities import Attack, Enemy


class ScriptedRng:
    def __init__(self, rolls):
        self._rolls = list(rolls)
        self._i = 0

    def randint(self, a, b):
        if self._i >= len(self._rolls):
            raise AssertionError(
                f'rng вызван {self._i + 1}-й раз, скрипт задан на {len(self._rolls)}')
        value = self._rolls[self._i]
        self._i += 1
        return value


def axe():
    return Attack('Топор', 5, 1, 'd8', 3, 'рубящий', range_ft=5)


def unit(name, side, *, hp=20, ac=14, attacks=None, dex=10, int_score=10,
         strategy=None, rng=None, speed=30):
    enemy = Enemy(name, hp, ac, attacks if attacks is not None else [axe()],
                  side, speed=speed, rng=rng)
    enemy.strategy = strategy or AggressiveStrategy()
    mod = (dex - 10) // 2
    enemy.ability_scores = {'dex': dex, 'int': int_score}
    enemy.ability_mods = {'dex': mod, 'int': (int_score - 10) // 2}
    return enemy


class TestInitiative(unittest.TestCase):

    def test_order_is_interleaved_not_side_by_side(self):
        # Броски в порядке обхода (сторона 0, потом 1): итоги 5, 18 и 12.
        # После сортировки сторона 0 не ходит целиком раньше стороны 1.
        sides = [
            [unit('A0', 0, dex=10), unit('A1', 0, dex=10)],
            [unit('B0', 1, dex=10)],
        ]
        order = living_initiative(sides, rng=ScriptedRng([5, 1, 18, 1, 12, 1]))
        names = [row[4].name for row in order]
        self.assertEqual(names, ['A1', 'B0', 'A0'])

    def test_same_roll_higher_dex_score_goes_first(self):
        # 14 и 15 дают один и тот же мод +2. Ничью рвёт значение Ловкости.
        slow = unit('Медленный', 0, dex=14)
        quick = unit('Быстрый', 1, dex=15)
        order = living_initiative([[slow], [quick]], rng=ScriptedRng([10, 1, 10, 1]))
        self.assertEqual([row[4].name for row in order], ['Быстрый', 'Медленный'])
        self.assertEqual(order[0][0], order[1][0])

    def test_same_dex_tie_break_roll(self):
        left = unit('А', 0, dex=12)
        right = unit('Б', 1, dex=12)
        order = living_initiative([[left], [right]], rng=ScriptedRng([10, 3, 10, 18]))
        self.assertEqual([row[4].name for row in order], ['Б', 'А'])

    def test_unit_killed_earlier_in_round_does_not_act(self):
        killer = unit('Убийца', 0, hp=30, ac=18, dex=18,
                      attacks=[Attack('Секира', 10, 1, 'd6', 0, 'рубящий')],
                      rng=ScriptedRng([15, 6]))
        victim = unit('Жертва', 1, hp=4, ac=10, dex=8, rng=ScriptedRng([]))
        outcome, log = run_round(
            [[killer], [victim]], ['А', 'Б'], {}, None, DecisionEngine(),
            auto_move=False, rng=ScriptedRng([18, 1, 5, 1]))
        self.assertEqual(outcome, 'over')
        self.assertFalse(victim.alive)
        self.assertNotIn('Жертва →', log)
        self.assertIn('Инициатива:', log)
        self.assertIn('УНИЧТОЖЕН', log)

    def test_mirrored_fights_are_roughly_balanced(self):
        rng = random.Random(20261125)
        fights = 200
        wins = [0, 0]
        first = [0, 0]
        decisive = 0
        for n in range(fights):
            sides = []
            for side in (0, 1):
                sides.append([
                    unit(f'S{side}_{i}', side, hp=12, ac=13,
                         attacks=[Attack('Топор', 5, 1, 'd10', 4, 'рубящий')],
                         dex=12, int_score=8, rng=rng)
                    for i in range(5)
                ])
            engine = DecisionEngine()
            first_side = None
            outcome = 'continue'
            log = ''
            for _ in range(25):
                outcome, log = run_round(
                    sides, ['А', 'Б'], {}, None, engine, auto_move=False, rng=rng)
                if first_side is None:
                    line = next(row for row in log.splitlines() if row.startswith('Инициатива:'))
                    leader = line.split(':', 1)[1].strip().split(',', 1)[0]
                    first_side = 0 if leader.startswith('S0') else 1
                if outcome != 'continue':
                    break
            first[first_side] += 1
            alive = [any(e.alive for e in side) for side in sides]
            if alive[0] != alive[1]:
                decisive += 1
                wins[0 if alive[0] else 1] += 1
            elif outcome == 'continue':
                self.fail(f'бой {n} не закончился за 25 раундов')
        self.assertGreater(decisive, fights * 0.8, f'мало результативных боёв: {decisive}')
        low = decisive * 0.35
        high_msg = (f'сторона 0 победила {wins[0]}/{decisive}, сторона 1 — {wins[1]}; '
                    f'первой ходила {first}')
        self.assertGreater(wins[0], low, high_msg)
        self.assertGreater(wins[1], low, high_msg)
        self.assertGreater(first[0], fights * 0.25, high_msg)
        self.assertGreater(first[1], fights * 0.25, high_msg)


class TestHealing(unittest.TestCase):

    def _cleric(self, rng, *, with_sword=False):
        attacks = [Attack('Лечение ран', 5, 1, 'd8', 3, '', range_ft=5)]
        if with_sword:
            attacks.append(Attack('Булава', 4, 1, 'd6', 2, 'дробящий', range_ft=5))
        cleric = unit('Жрец', 0, hp=20, attacks=attacks, strategy=SupportStrategy(), rng=rng)
        return cleric

    def test_execute_strikes_heals_instead_of_damaging(self):
        cleric = self._cleric(ScriptedRng([4]))
        ally = unit('Воин', 0, hp=20)
        ally.hp = 10
        lines, killed = execute_strikes(
            cleric, ally, [cleric.attacks[0]],
            [[cleric, ally], []], {}, None)
        self.assertEqual(ally.hp, 17, '4+3 лечения, а не 7 урона (20 → 13)')
        self.assertFalse(killed)
        self.assertIn('ЛЕЧЕНИЕ', lines[0])
        self.assertNotIn('ПОПАДАНИЕ', lines[0])

    def test_heal_is_capped_at_max_hp_and_skips_attack_roll(self):
        cleric = self._cleric(ScriptedRng([6]))
        ally = unit('Воин', 0, hp=20)
        ally.hp = 18
        execute_strikes(cleric, ally, [cleric.attacks[0]], [[cleric, ally], []], {}, None)
        self.assertEqual(ally.hp, 20)

    def test_support_without_heal_never_targets_allies(self):
        supporter = unit('Сержант', 0, hp=20,
                         attacks=[Attack('Меч', 5, 1, 'd8', 3, 'рубящий')],
                         strategy=SupportStrategy())
        ally = unit('Раненый', 0, hp=20)
        ally.hp = 1
        foe = unit('Орк', 1, hp=15)
        strategy = SupportStrategy()
        self.assertIs(strategy.select_target(supporter, [[supporter, ally], [foe]], set()), foe)
        self.assertIsNone(strategy.select_target(supporter, [[supporter, ally]], set()))

    def test_healer_restores_ally_during_round(self):
        cleric = self._cleric(ScriptedRng([6]), with_sword=True)
        ally = unit('Воин', 0, hp=20, dex=10, ac=18)
        ally.hp = 10
        # Натуральная 1: орк, ходящий следом, не снимает только что вылеченные хиты.
        foe = unit('Орк', 1, hp=30, ac=18, dex=8, rng=ScriptedRng([1]))
        run_round([[cleric, ally], [foe]], ['А', 'Б'], {}, None, DecisionEngine(),
                  auto_move=False, rng=ScriptedRng([20, 1, 1, 1, 2, 1]))
        self.assertEqual(ally.hp, 19, 'кость 6 + мод 3, без броска против КД')


class TestCritModeRound(unittest.TestCase):

    def test_dice_only_crit_mode_reaches_the_round(self):
        attacker = unit(
            'А', 0, hp=40, ac=18, dex=20,
            attacks=[Attack('Меч', 0, 1, 'd6', 2, 'рубящий')],
            rng=ScriptedRng([20, 1, 20, 6, 1]))
        target = unit('Б', 1, hp=30, ac=10, dex=8, rng=random.Random(1))
        run_round([[attacker], [target]], ['А', 'Б'], {}, None, DecisionEngine(),
                  auto_move=False, crit_mode='dice_only')
        self.assertEqual(target.hp, 21, 'крит «только кости»: 6+1+2, не (6+2)*2')


if __name__ == '__main__':
    unittest.main(verbosity=2)
