"""События раунда, прежний текст лога и экспорт JSON/Markdown/текста."""
import inspect
import os
import random
import tempfile
import unittest

from battle_map_model import BattleMap
from battle_round import run_round
from battle_strategies import AggressiveStrategy, SupportStrategy
from combat_core import execute_strikes, legendary_after_turn
from combat_log import (conceal_enemy_hp, dump_log, event_visible, events_from_json,
                        load_events, map_marks, render_json, render_log, render_markdown)
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


def axe(name='Топор', bonus=4, count=1, dice='d6', mod=2, dtype='рубящий', reach=5,
        extra=None):
    return Attack(name, bonus, count, dice, mod, dtype, range_ft=reach, extra_damage=extra)


def unit(name, side, *, hp=20, ac=14, attacks=None, dex=10, rng=None, speed=30,
         regen=0, strategy=None):
    enemy = Enemy(name, hp, ac, attacks if attacks is not None else [axe()],
                  side, speed=speed, regen=regen, rng=rng)
    enemy.strategy = strategy or AggressiveStrategy()
    mod = (dex - 10) // 2
    enemy.ability_scores = {'dex': dex, 'int': 10}
    enemy.ability_mods = {'dex': mod, 'int': 0}
    return enemy


class TestStrikeEvents(unittest.TestCase):

    def test_hit_miss_crit_and_natural_one(self):
        # Попадание: 10+5=15 против КД 12, кость 4 + мод 2 = 6.
        attacker = unit('Боец', 0, ac=18, rng=ScriptedRng([10, 4]),
                        attacks=[axe('Секира', bonus=5, mod=2)])
        target = unit('Цель', 1, hp=20, ac=12, rng=ScriptedRng([]))
        events = []
        lines, killed = execute_strikes(
            attacker, target, [attacker.attacks[0]], [[attacker], [target]], {}, None,
            events=events)
        self.assertFalse(killed)
        self.assertEqual(lines, [
            'Боец → Цель (Секира: 15 vs AC 12) - ПОПАДАНИЕ! 6 урона (рубящий)'])
        self.assertEqual(render_log(events), lines[0])
        hit = events[0]
        self.assertEqual(hit.kind, 'attack')
        self.assertEqual(hit.result, 'hit')
        self.assertFalse(hit.crit)
        self.assertEqual(hit.natural, 10)
        self.assertEqual(hit.modifier, 5)
        self.assertEqual(hit.attack_total, 15)
        self.assertEqual(hit.ac, 12)
        self.assertEqual(hit.damages[0].damage_type, 'рубящий')
        self.assertEqual(hit.damages[0].raw, 6)
        self.assertEqual(hit.damages[0].final, 6)
        self.assertEqual((hit.hp_before, hit.hp_after), (20, 14))

        # Промах без натуральной 1: кость урона не кидается.
        misser = unit('Лучник', 0, rng=ScriptedRng([3]), attacks=[axe('Лук', bonus=1)])
        dodger = unit('Плут', 1, hp=11, ac=18, rng=ScriptedRng([]))
        missed = []
        execute_strikes(misser, dodger, [misser.attacks[0]], [[misser], [dodger]], {}, None,
                        events=missed)
        self.assertEqual(missed[0].result, 'miss')
        self.assertEqual(missed[0].natural, 3)
        self.assertEqual(missed[0].attack_total, 4)
        self.assertEqual(missed[0].damages, [])
        self.assertEqual(dodger.hp, 11)
        self.assertEqual(
            missed[0].text,
            'Лучник → Плут (Лук: 4 vs AC 18) - ПРОМАХ!')

        # Натуральная 1 промахивается, даже если итог бьёт КД. Текст — прежний «ПРОМАХ».
        fumbler = unit('Неудачник', 0, rng=ScriptedRng([1]),
                       attacks=[axe('Дубина', bonus=5)])
        victim = unit('Орк', 1, hp=30, ac=10, rng=ScriptedRng([]))
        nat1 = []
        execute_strikes(fumbler, victim, [fumbler.attacks[0]], [[fumbler], [victim]], {}, None,
                        events=nat1)
        self.assertEqual(nat1[0].result, 'nat1')
        self.assertEqual(nat1[0].natural, 1)
        self.assertEqual(nat1[0].modifier, 5)
        self.assertEqual(nat1[0].attack_total, 6)
        self.assertFalse(nat1[0].crit)
        self.assertEqual(victim.hp, 30)
        self.assertEqual(nat1[0].text, 'Неудачник → Орк (Дубина: 6 vs AC 10) - ПРОМАХ!')
        self.assertNotIn('натуральн', nat1[0].text)

        # Крит double_all: (6+2)*2 = 16, КД 30 не мешает натуральной 20.
        critter = unit('Убийца', 0, rng=ScriptedRng([20, 6]),
                       attacks=[axe('Секира', bonus=3, mod=2)])
        tough = unit('Танк', 1, hp=40, ac=30, rng=ScriptedRng([]))
        crits = []
        execute_strikes(critter, tough, [critter.attacks[0]], [[critter], [tough]], {}, None,
                        events=crits)
        self.assertEqual(crits[0].result, 'crit')
        self.assertTrue(crits[0].crit)
        self.assertEqual(crits[0].natural, 20)
        self.assertEqual(crits[0].damages[0].raw, 16)
        self.assertEqual(crits[0].damages[0].final, 16)
        self.assertIn('КРИТИЧЕСКИЙ УДАР', crits[0].text)
        self.assertIn('16 урона (рубящий)', crits[0].text)
        self.assertEqual(tough.hp, 24)

    def test_resistance_and_extra_damage_keep_raw_and_final(self):
        attacker = unit('Боец', 0, rng=ScriptedRng([12, 5]),
                        attacks=[axe(bonus=4, mod=2)])
        target = unit('Щит', 1, hp=20, ac=10, rng=ScriptedRng([]))
        target.resistances = ['рубящий']
        events = []
        lines, _killed = execute_strikes(
            attacker, target, [attacker.attacks[0]], [[attacker], [target]], {}, None,
            events=events)
        part = events[0].damages[0]
        self.assertEqual((part.raw, part.final), (7, 3))
        self.assertIn('сопротивление: рубящий', part.note)
        self.assertIn('7 урона (рубящий)', lines[0])
        self.assertIn('→ 3 (сопротивление: рубящий)', lines[0])
        self.assertEqual(target.hp, 17)
        self.assertEqual((events[0].hp_before, events[0].hp_after), (20, 17))

        fire = {'dice_count': 1, 'dice_type': 'd6', 'modifier': 0, 'damage_type': 'огонь'}
        burner = unit('Дракончик', 0, rng=ScriptedRng([15, 4, 3]),
                      attacks=[axe('Укус', bonus=4, mod=2, extra=[fire])])
        immune = unit('Ифрит', 1, hp=30, ac=10, rng=ScriptedRng([]))
        immune.immunities = ['огонь']
        extra_events = []
        extra_lines, _killed = execute_strikes(
            burner, immune, [burner.attacks[0]], [[burner], [immune]], {}, None,
            events=extra_events)
        primary, bonus = extra_events[0].damages
        self.assertFalse(primary.extra)
        self.assertEqual((primary.raw, primary.final), (6, 6))
        self.assertTrue(bonus.extra)
        self.assertEqual(bonus.damage_type, 'огонь')
        self.assertEqual((bonus.raw, bonus.final), (3, 0))
        self.assertIn('иммунитет: огонь', bonus.note)
        self.assertIn('+ 0 (огонь)', extra_lines[0])
        self.assertEqual(immune.hp, 24)

    def test_heal_event_skips_attack_roll(self):
        cleric = unit('Жрец', 0, hp=20, rng=ScriptedRng([4]),
                      attacks=[Attack('Лечение ран', 5, 1, 'd8', 3, '', range_ft=5)],
                      strategy=SupportStrategy())
        ally = unit('Воин', 0, hp=20)
        ally.hp = 10
        events = []
        lines, killed = execute_strikes(
            cleric, ally, [cleric.attacks[0]], [[cleric, ally], []], {}, None, events=events)
        self.assertFalse(killed)
        self.assertEqual(lines[0], 'Жрец → Воин (Лечение ран) - ЛЕЧЕНИЕ! +7 HP (17/20)')
        heal = events[0]
        self.assertEqual(heal.kind, 'heal')
        self.assertEqual(heal.result, 'heal')
        self.assertEqual(heal.heal_amount, 7)
        self.assertEqual((heal.hp_before, heal.hp_after, heal.max_hp), (10, 17, 20))
        self.assertIsNone(heal.natural)
        self.assertEqual(ally.hp, 17)

    def test_death_is_its_own_event(self):
        attacker = unit('Боец', 0, rng=ScriptedRng([14, 6]),
                        attacks=[axe(bonus=5, mod=3)])
        target = unit('Слабак', 1, hp=5, ac=10, rng=ScriptedRng([]))
        events = []
        lines, killed = execute_strikes(
            attacker, target, [attacker.attacks[0]], [[attacker], [target]], {}, None,
            events=events)
        self.assertTrue(killed)
        self.assertFalse(target.alive)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].kind, 'attack')
        self.assertEqual(events[0].hp_after, 0)
        self.assertEqual(events[1].kind, 'death')
        self.assertEqual(events[1].result, 'death')
        self.assertEqual(events[1].text, '☠️ Слабак УНИЧТОЖЕН!')
        self.assertEqual(lines[1], events[1].text)

    def test_legendary_action_event(self):
        goblin = unit('Гоблин', 0, hp=20, ac=10, rng=ScriptedRng([]))
        tail = axe('Хвост', bonus=8, dice='d8', mod=4, dtype='дробящий', reach=10)
        dragon = unit('Дракон', 1, hp=80, ac=18, attacks=[tail], rng=ScriptedRng([18, 5]))
        dragon.legendary_actions = {
            'per_round': 3,
            'options': [
                {'name': 'Обнаружение', 'cost': 1, 'desc': 'проверка', 'attack': None,
                 'count': 1, 'usable': False},
                {'name': 'Атака хвостом', 'cost': 1, 'desc': 'атака хвостом', 'attack': 'Хвост',
                 'count': 1, 'usable': True},
            ],
        }
        events = []
        lines = legendary_after_turn(goblin, [[goblin], [dragon]], {}, None, events=events)
        self.assertEqual(dragon.legendary_remaining, 2)
        self.assertEqual(events[0].kind, 'legendary')
        self.assertEqual(events[0].action, 'Атака хвостом')
        self.assertEqual(events[0].cost, 1)
        self.assertTrue(events[0].legendary)
        self.assertIn('легендарное действие', lines[0])
        self.assertIn('Атака хвостом', lines[0])
        attack = next(event for event in events if event.kind == 'attack')
        self.assertTrue(attack.legendary)
        self.assertEqual(attack.natural, 18)
        self.assertEqual(attack.modifier, 8)
        self.assertEqual(attack.attack_total, 26)
        self.assertEqual(attack.result, 'hit')
        self.assertEqual(attack.reason, 'Атака хвостом')
        self.assertEqual(goblin.hp, 11)
        self.assertEqual(lines, [event.text for event in events if event.text is not None])


class TestRoundLog(unittest.TestCase):

    def test_rendered_text_matches_legacy_round(self):
        killer = unit('Убийца', 0, hp=30, ac=14, dex=10, rng=ScriptedRng([12, 5]),
                      attacks=[axe('Топор', bonus=4, mod=2)])
        victim = unit('Жертва', 1, hp=20, ac=10, dex=10, rng=ScriptedRng([1]),
                      attacks=[axe('Кинжал', bonus=5, dice='d4', mod=1, dtype='колющий')])
        result = run_round(
            [[killer], [victim]], ['А', 'Б'], {}, None, DecisionEngine(),
            auto_move=False, rng=ScriptedRng([15, 3, 8, 1]), round_no=1)
        outcome, text = result
        self.assertEqual(outcome, 'continue')
        self.assertEqual(text, render_log(result.events))
        expected = (
            '=== НОВЫЙ РАУНД БОЯ ===\n'
            'Инициатива: Убийца (15), Жертва (8)\n'
            'Убийца → Жертва (Топор: 16 vs AC 10) - ПОПАДАНИЕ! 7 урона (рубящий)\n'
            'Жертва → Убийца (Кинжал: 6 vs AC 14) - ПРОМАХ!\n'
            '\n'
            '\nБитва продолжается: А vs Б\n'
        )
        self.assertEqual(text, expected)
        self.assertEqual(victim.hp, 13)
        initiative = next(event for event in result.events if event.kind == 'initiative')
        self.assertEqual(initiative.rolls[0].natural, 15)
        self.assertEqual(initiative.rolls[0].modifier, 0)
        self.assertEqual(initiative.rolls[0].total, 15)
        self.assertEqual(initiative.rolls[0].tie_roll, 3)
        self.assertEqual(initiative.rolls[1].name, 'Жертва')
        hit = next(event for event in result.events if event.result == 'hit')
        self.assertEqual(hit.round, 1)
        self.assertEqual(hit.natural, 12)
        nat1 = next(event for event in result.events if event.result == 'nat1')
        self.assertEqual(nat1.natural, 1)
        self.assertEqual(nat1.actor, 'Жертва')

    def test_movement_event_on_the_map(self):
        random.seed(1)
        battle_map = BattleMap(20, 10)
        left = unit('Мечник А', 0, hp=30, ac=16, speed=30, dex=12,
                    rng=random.Random(1), attacks=[axe('Меч', bonus=6, mod=2)])
        right = unit('Мечник Б', 1, hp=30, ac=16, speed=30, dex=12,
                     rng=random.Random(1), attacks=[axe('Меч', bonus=6, mod=2)])
        battle_map.place(left, 0, 0)
        battle_map.place(right, 6, 0)
        result = run_round(
            [[left], [right]], ['А', 'Б'], {}, battle_map, DecisionEngine(),
            auto_move=True, rng=random.Random(2), round_no=2)
        moves = [event for event in result.events if event.kind == 'move']
        self.assertTrue(moves)
        move = moves[0]
        self.assertNotEqual(move.from_pos, move.to_pos)
        self.assertEqual(move.round, 2)
        self.assertIn('перемещается', move.text)
        self.assertIn(move.text, result.text)
        self.assertNotIn('не может достать', result.text)
        self.assertTrue('ПОПАДАНИЕ' in result.text or 'ПРОМАХ' in result.text)
        self.assertEqual(battle_map.distance_ft(left, right), 5.0)
        marks = map_marks(result.events)
        self.assertTrue(any(mark['style'] in ('hit', 'miss', 'crit', 'nat1') for mark in marks))
        self.assertFalse(any(mark['style'] == 'move' for mark in marks))
        focused = map_marks([move], include_moves=True)
        self.assertEqual(focused[0]['style'], 'move')

    def test_json_and_files_round_trip(self):
        left = unit('А', 0, rng=ScriptedRng([11, 4]), attacks=[axe()])
        right = unit('Б', 1, hp=18, ac=12, rng=ScriptedRng([2]), attacks=[axe(bonus=0)])
        result = run_round(
            [[left], [right]], ['А', 'Б'], {}, None, DecisionEngine(),
            auto_move=False, rng=ScriptedRng([16, 1, 9, 2]), round_no=4)
        restored = events_from_json(render_json(result.events))
        self.assertEqual(restored, result.events)
        self.assertEqual(render_log(restored), result.text)
        with tempfile.TemporaryDirectory() as tmp:
            json_path = os.path.join(tmp, 'log.json')
            text_path = os.path.join(tmp, 'log.txt')
            md_path = os.path.join(tmp, 'log.md')
            self.assertEqual(dump_log(result.events, json_path), render_json(result.events))
            self.assertEqual(dump_log(result.events, text_path), result.text)
            markdown = dump_log(result.events, md_path)
            self.assertEqual(markdown, render_markdown(result.events))
            self.assertEqual(load_events(json_path), result.events)
            with open(text_path, encoding='utf-8') as handle:
                self.assertEqual(handle.read(), result.text)
            with open(md_path, encoding='utf-8') as handle:
                written = handle.read()
            self.assertIn('## Раунд 4', written)
            self.assertIn('бросок d20', written)
            self.assertEqual(written, markdown)

    def test_player_view_hides_enemy_hp_only(self):
        ally = unit('Воин', 0, hp=20)
        ally.hp = 10
        foe = unit('Орк', 1, hp=20, ac=10)
        events = []
        execute_strikes(
            unit('Боец', 0, rng=ScriptedRng([12, 4]), attacks=[axe(bonus=4, mod=2)]),
            foe, [axe(bonus=4, mod=2)], [[], [foe]], {}, None, events=events)
        hidden = conceal_enemy_hp(events[0], viewer_side=0)
        self.assertIsNone(hidden.hp_before)
        self.assertIsNone(hidden.hp_after)
        self.assertIsNone(hidden.max_hp)
        self.assertEqual(hidden.result, events[0].result)
        self.assertEqual(hidden.damages[0].final, events[0].damages[0].final)
        shown = conceal_enemy_hp(events[0], viewer_side=1)
        self.assertEqual(shown.hp_after, events[0].hp_after)

        heal_events = []
        cleric = unit('Жрец', 0, rng=ScriptedRng([4]),
                      attacks=[Attack('Лечение ран', 5, 1, 'd8', 3, '')],
                      strategy=SupportStrategy())
        execute_strikes(cleric, ally, [cleric.attacks[0]], [[cleric, ally], []], {}, None,
                        events=heal_events)
        secret = conceal_enemy_hp(heal_events[0], viewer_side=1)
        self.assertIsNone(secret.hp_after)
        self.assertNotIn('17/20', secret.text)
        self.assertIn('+7 HP', secret.text)
        own = conceal_enemy_hp(heal_events[0], viewer_side=0)
        self.assertEqual(own.hp_after, 17)
        self.assertIn('17/20', own.text)

    def test_filters_by_side_creature_kind_and_search(self):
        hit = self._sample()[0]
        self.assertTrue(event_visible(hit, kind='hit'))
        self.assertTrue(event_visible(hit, kind='all', query='топор'))
        self.assertFalse(event_visible(hit, kind='miss'))
        self.assertFalse(event_visible(hit, kind='heal'))
        self.assertFalse(event_visible(hit, query='регенерация'))
        death = [event for event in self._killed() if event.kind == 'death'][0]
        self.assertTrue(event_visible(death, kind='death'))
        self.assertFalse(event_visible(death, kind='hit'))
        self.assertTrue(event_visible(hit, side=hit.actor_side))
        self.assertFalse(event_visible(hit, side=9))
        self.assertTrue(event_visible(hit, creature_id=hit.actor_id))
        self.assertFalse(event_visible(hit, creature_id=-1))

    def test_core_modules_stay_gui_free(self):
        import ast
        import battle_round
        import combat_core
        import combat_log
        for module in (battle_round, combat_core, combat_log):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or '']
                else:
                    continue
                for name in names:
                    self.assertFalse(
                        name == 'tkinter' or name.startswith('tkinter.')
                        or name.startswith('PyQt'),
                        name)

    def _sample(self):
        attacker = unit('Боец', 0, rng=ScriptedRng([10, 4]), attacks=[axe('Топор')])
        target = unit('Цель', 1, ac=10, rng=ScriptedRng([]))
        events = []
        execute_strikes(attacker, target, [attacker.attacks[0]],
                        [[attacker], [target]], {}, None, events=events)
        return events

    def _killed(self):
        attacker = unit('Боец', 0, rng=ScriptedRng([14, 6]), attacks=[axe(bonus=5, mod=3)])
        target = unit('Слабак', 1, hp=4, ac=10, rng=ScriptedRng([]))
        events = []
        execute_strikes(attacker, target, [attacker.attacks[0]],
                        [[attacker], [target]], {}, None, events=events)
        return events


if __name__ == '__main__':
    unittest.main(verbosity=2)
