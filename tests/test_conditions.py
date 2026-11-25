"""Состояния, спасброски, дыхание, захват, журнал и отмена.

Запуск вместе с остальными: QT_QPA_PLATFORM=offscreen python -m unittest
"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from battle_history import BattleHistory, apply_snapshot, capture_battle
from battle_map_model import BattleMap
from battle_round import run_round
from combat_core import modify_damage
from combat_log import CombatEvent, event_visible
from conditions import (apply_condition, attack_modifiers, auto_fail_save,
                        effective_speed, has_condition, is_incapacitated,
                        permanent_duration, save_bonus, saving_throw,
                        set_exhaustion, tick_rounds_and_saves, try_stand,
                        turn_bounds)
from decision_engine import DecisionEngine
from effects import (consume_recharge, ensure_recharge, execute_effect,
                     parse_special_effect, roll_recharges)
from entities import Attack, Enemy
from tests.test_bestiary_import import load


class Scripted:
    def __init__(self, rolls):
        self._rolls = list(rolls)
        self._i = 0

    def randint(self, a, b):
        if self._i >= len(self._rolls):
            raise AssertionError(f'лишний бросок, скрипт {self._rolls}')
        value = self._rolls[self._i]
        self._i += 1
        return value


def unit(name, side, *, hp=30, ac=12, speed=30, rng=None, attacks=None):
    enemy = Enemy(name, hp, ac, attacks or [Attack('Удар', 5, 1, 'd6', 2, 'дробящий')],
                  side, speed=speed, rng=rng)
    enemy.ability_scores = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}
    enemy.ability_mods = {key: 0 for key in enemy.ability_scores}
    return enemy


class TestAttackAdvantage(unittest.TestCase):

    def test_advantage_keeps_higher_of_two_d20(self):
        fighter = unit('Боец', 0, rng=Scripted([3, 18, 4]), attacks=[
            Attack('Меч', 5, 1, 'd6', 2, 'рубящий')])
        roll = fighter.perform_attack(fighter.attacks[0], 10, advantage=True)
        self.assertEqual(roll.naturals, [3, 18])
        self.assertEqual(roll.natural, 18)
        self.assertEqual(roll.advantage, 'advantage')
        self.assertEqual(roll.total, 23)
        self.assertTrue(roll.hit)
        self.assertEqual(roll.damage, 6)

    def test_disadvantage_keeps_lower_and_nat1_misses(self):
        fighter = unit('Боец', 0, rng=Scripted([18, 1]), attacks=[
            Attack('Меч', 5, 1, 'd6', 2, 'рубящий')])
        roll = fighter.perform_attack(fighter.attacks[0], 10, disadvantage=True)
        self.assertEqual(roll.naturals, [18, 1])
        self.assertEqual(roll.natural, 1)
        self.assertFalse(roll.hit)
        self.assertEqual(roll.damage, 0)
        self.assertEqual(roll.advantage, 'disadvantage')

    def test_advantage_and_disadvantage_cancel_to_one_die(self):
        fighter = unit('Боец', 0, rng=Scripted([12, 4]), attacks=[
            Attack('Меч', 2, 1, 'd6', 1, 'рубящий')])
        roll = fighter.perform_attack(
            fighter.attacks[0], 10, advantage=True, disadvantage=True)
        self.assertEqual(roll.naturals, [12])
        self.assertEqual(roll.advantage, 'cancel')
        self.assertEqual(roll.natural, 12)
        self.assertEqual(roll.total, 14)

    def test_paralyzed_within_5_feet_is_auto_crit_on_a_hit(self):
        victim = unit('Жертва', 1)
        apply_condition(victim, 'paralyzed')
        adv, dis, crit = attack_modifiers(unit('Боец', 0), victim, 5)
        self.assertTrue(adv)
        self.assertFalse(dis)
        self.assertTrue(crit)
        fighter = unit('Боец', 0, rng=Scripted([10, 3]), attacks=[
            Attack('Меч', 5, 1, 'd6', 2, 'рубящий')])
        roll = fighter.perform_attack(fighter.attacks[0], 10, force_crit=True)
        self.assertTrue(roll.hit)
        self.assertTrue(roll.critical)
        self.assertEqual(roll.damage, 10)


class TestSavingThrows(unittest.TestCase):

    def test_natural_20_does_not_auto_succeed_and_natural_1_can_pass(self):
        hero = unit('Герой', 0, rng=Scripted([20]))
        fail = saving_throw(hero, 'dex', 25)
        self.assertFalse(fail.success)
        self.assertEqual(fail.total, 20)
        hero._rng = Scripted([1])
        hero.saves = {'Ловкость': '+10'}
        passed = saving_throw(hero, 'dex', 11)
        self.assertTrue(passed.success)
        self.assertEqual(passed.natural, 1)
        self.assertEqual(passed.total, 11)
        self.assertEqual(save_bonus(hero, 'dex'), 10)

    def test_unlisted_save_is_only_the_ability_modifier(self):
        hero = unit('Герой', 0)
        hero.ability_mods['wis'] = 3
        self.assertEqual(save_bonus(hero, 'wis'), 3)

    def test_legendary_resistance_spends_on_a_disabling_fail_only(self):
        dragon = unit('Дракон', 0, hp=200, rng=Scripted([2]))
        dragon.legendary_resistance = {'count': 1, 'name': 'Легендарное сопротивление'}
        effect, warning = parse_special_effect(
            'Взгляд',
            'Цель должна преуспеть в спасброске Мудрости Сл 15, иначе станет парализованной.')
        self.assertIsNone(warning)
        events = execute_effect(dragon, effect, [[dragon], [unit('Жертва', 1, rng=Scripted([2]))]],
                                set(), None, focus=None)
        victim = None
        # execute builds its own target list; rebuild with a known victim
        victim = unit('Жертва', 1, hp=40, rng=Scripted([2]))
        victim.legendary_resistance = {'count': 2, 'name': 'Легендарное сопротивление'}
        events = execute_effect(
            dragon, effect, [[dragon], [victim]], set(), None)
        self.assertFalse(has_condition(victim, 'paralyzed'))
        self.assertEqual(victim.legendary_resistance_remaining, 1)
        self.assertTrue(any(event.resistance_used for event in events))

        victim.legendary_resistance_remaining = 1
        puff, _warn = parse_special_effect(
            'Искра',
            'Существо совершает спасбросок Ловкости Сл 30, получая урон огнём 1 (1к4) при провале.')
        victim._rng = Scripted([1])
        dragon._rng = Scripted([1])
        events = execute_effect(dragon, puff, [[dragon], [victim]], set(), None)
        self.assertEqual(victim.legendary_resistance_remaining, 1)
        self.assertTrue(any(event.kind == 'save' and event.result == 'fail' for event in events))


class TestConditionEffects(unittest.TestCase):

    def setUp(self):
        self.attacker = unit('Атакующий', 0)
        self.target = unit('Цель', 1)

    def test_each_condition_key_effect(self):
        cases = [
            ('blinded', self.attacker, False, True),
            ('poisoned', self.attacker, False, True),
            ('restrained', self.attacker, False, True),
            ('prone', self.attacker, False, True),
            ('invisible', self.attacker, True, False),
            ('blinded', self.target, True, False),
            ('restrained', self.target, True, False),
            ('paralyzed', self.target, True, False),
            ('stunned', self.target, True, False),
            ('petrified', self.target, True, False),
            ('invisible', self.target, False, True),
        ]
        for condition_id, who, expect_adv, expect_dis in cases:
            bearer = unit(who.name, who.side)
            other_a = unit('А', 0)
            other_b = unit('Б', 1)
            apply_condition(bearer, condition_id)
            if who is self.attacker:
                adv, dis, _crit = attack_modifiers(bearer, other_b, 30)
            else:
                adv, dis, _crit = attack_modifiers(other_a, bearer, 30)
            self.assertEqual(adv, expect_adv, condition_id)
            self.assertEqual(dis, expect_dis, condition_id)

        self.assertEqual(effective_speed(self._with('grappled')), 0)
        self.assertEqual(effective_speed(self._with('restrained')), 0)
        self.assertEqual(effective_speed(self._with('paralyzed')), 0)
        self.assertEqual(effective_speed(self._with('stunned')), 0)
        self.assertEqual(effective_speed(self._with('petrified')), 0)
        self.assertEqual(effective_speed(self._with('unconscious')), 0)
        self.assertTrue(is_incapacitated(self._with('incapacitated')))
        self.assertTrue(is_incapacitated(self._with('stunned')))
        self.assertTrue(auto_fail_save(self._with('paralyzed'), 'str'))
        self.assertTrue(auto_fail_save(self._with('stunned'), 'dex'))
        self.assertFalse(auto_fail_save(self._with('paralyzed'), 'wis'))
        prone_near = self._with('prone')
        adv, dis, _crit = attack_modifiers(unit('А', 0), prone_near, 5)
        self.assertTrue(adv and not dis)
        adv, dis, _crit = attack_modifiers(unit('А', 0), prone_near, 10)
        self.assertTrue(dis and not adv)
        unconscious = self._with('unconscious')
        self.assertTrue(has_condition(unconscious, 'prone'))
        adv, dis, crit = attack_modifiers(unit('А', 0), unconscious, 5)
        self.assertTrue(adv and not dis and crit)
        deaf = self._with('deafened')
        adv, dis, _crit = attack_modifiers(deaf, unit('Б', 1), 5)
        self.assertFalse(adv or dis)
        charmed = unit('Очарованный', 0)
        source = unit('Источник', 1)
        apply_condition(charmed, 'charmed', source=source)
        other = unit('Другой', 1)
        charmed.strategy = __import__('battle_strategies', fromlist=['AggressiveStrategy']).AggressiveStrategy()
        source.strategy = charmed.strategy
        other.strategy = charmed.strategy
        decision = DecisionEngine().decide(charmed, [[charmed], [source, other]], set())
        self.assertIs(decision.target, other)
        frightened = unit('Трус', 0, speed=30)
        apply_condition(frightened, 'frightened', source=source)
        adv, dis, _crit = attack_modifiers(frightened, other, 5)
        self.assertTrue(dis and not adv)
        frightened.pos = (0, 0)
        source.pos = (6, 0)
        other.pos = (1, 0)
        frightened.strategy = charmed.strategy
        decision = DecisionEngine().decide(frightened, [[frightened], [source, other]], set())
        self.assertIs(decision.target, other)
        tired = unit('Уставший', 0, speed=30)
        set_exhaustion(tired, 2)
        self.assertEqual(effective_speed(tired), 15)
        set_exhaustion(tired, 3)
        adv, dis, _crit = attack_modifiers(tired, unit('Б', 1), 5)
        self.assertTrue(dis)
        hero = unit('Герой', 0, rng=Scripted([10, 4]))
        set_exhaustion(hero, 3)
        roll = saving_throw(hero, 'wis', 15)
        self.assertEqual(roll.advantage, 'disadvantage')
        set_exhaustion(tired, 5)
        self.assertEqual(effective_speed(tired), 0)
        set_exhaustion(tired, 6)
        self.assertFalse(tired.alive)
        stone = unit('Статуя', 1, hp=20)
        apply_condition(stone, 'petrified')
        final, note = modify_damage(stone, 10, 'огонь')
        self.assertEqual(final, 5)
        self.assertIn('окаменен', note)
        final, note = modify_damage(stone, 8, 'яд')
        self.assertEqual(final, 0)

    def _with(self, condition_id):
        enemy = unit(condition_id, 1, speed=30)
        apply_condition(enemy, condition_id)
        return enemy

    def test_prone_stand_costs_half_speed_then_attack_is_normal(self):
        enemy = unit('Лежащий', 0, speed=30)
        apply_condition(enemy, 'prone')
        stood = try_stand(enemy)
        self.assertIsNotNone(stood)
        self.assertEqual(stood[0], 15)
        self.assertEqual(enemy.moved_ft, 15)
        self.assertFalse(has_condition(enemy, 'prone'))

    def test_durations_rounds_bounds_and_repeat_save(self):
        target = unit('Цель', 1, rng=Scripted([1, 18]))
        source = unit('Источник', 0)
        apply_condition(target, 'poisoned', source=source, duration={
            'kind': 'rounds', 'whose': 'target', 'rounds': 1,
            'ability': None, 'dc': None})
        tick_rounds_and_saves(target, [[source], [target]])
        self.assertFalse(has_condition(target, 'poisoned'))

        apply_condition(target, 'speed_zero', source=source, duration={
            'kind': 'start', 'whose': 'source', 'rounds': None,
            'ability': None, 'dc': None})
        self.assertEqual(turn_bounds(target, [[source], [target]], 'start'), [])
        removed = turn_bounds(source, [[source], [target]], 'start')
        self.assertEqual(len(removed), 1)
        self.assertFalse(has_condition(target, 'speed_zero'))

        apply_condition(target, 'poisoned', duration={
            'kind': 'end', 'whose': 'target', 'rounds': None,
            'ability': None, 'dc': None})
        self.assertEqual(turn_bounds(source, [[source], [target]], 'end'), [])
        self.assertTrue(turn_bounds(target, [[source], [target]], 'end'))
        self.assertFalse(has_condition(target, 'poisoned'))

        apply_condition(target, 'frightened', source=source, duration={
            'kind': 'repeat_save', 'whose': 'target', 'rounds': 10,
            'ability': 'wis', 'dc': 15})
        tick_rounds_and_saves(target, [[source], [target]])
        self.assertTrue(has_condition(target, 'frightened'))
        tick_rounds_and_saves(target, [[source], [target]])
        self.assertFalse(has_condition(target, 'frightened'))

    def test_death_clears_conditions_and_grapples(self):
        grappler = unit('Змея', 0)
        victim = unit('Жертва', 1, hp=5)
        apply_condition(victim, 'grappled', source=grappler, escape_dc=16)
        apply_condition(grappler, 'poisoned')
        grappler.take_damage(99)
        self.assertFalse(grappler.alive)
        self.assertEqual(grappler.conditions, [])
        from conditions import release_grapples_from
        release_grapples_from(grappler, [[grappler], [victim]])
        self.assertFalse(has_condition(victim, 'grappled'))


class TestParsedActions(unittest.TestCase):

    def test_ancient_red_breath_half_damage_and_recharge(self):
        monster = load('ancient-red-dragon.html')
        breath = next(item for item in monster['special_actions']
                      if 'дыхание' in item['name'].lower())
        effect = breath['effect']
        self.assertEqual(effect['ability'], 'dex')
        self.assertEqual(effect['dc'], 24)
        self.assertTrue(effect['half_on_success'])
        self.assertEqual(effect['area'], 'cone')
        self.assertEqual(effect['range_ft'], 90)
        self.assertEqual(effect['recharge'], {'low': 5, 'high': 6})
        self.assertEqual(effect['damage']['dice_count'], 26)
        self.assertEqual(effect['damage']['dice_type'], 'd6')
        fright = next(item for item in monster['special_actions']
                      if 'присутств' in item['name'].lower())
        self.assertTrue(fright['effect']['supplement'])
        self.assertIn('frightened', fright['effect']['conditions'])
        self.assertEqual(fright['effect']['duration']['kind'], 'repeat_save')
        self.assertEqual(fright['effect']['dc'], 21)

        small = dict(effect)
        small['dc'] = 10
        small['damage'] = {'dice_count': 2, 'dice_type': 'd6', 'modifier': 0,
                           'damage_type': 'огонь'}
        dragon = unit('Дракон', 0, hp=100, rng=Scripted([3, 3]))
        dragon.special_actions = [breath]
        victim = unit('Жертва', 1, hp=80, rng=Scripted([18]))
        victim.ability_mods['dex'] = 0
        battle = BattleMap(20, 10)
        battle.place(dragon, 0, 0)
        battle.place(victim, 2, 0)
        events = execute_effect(dragon, small, [[dragon], [victim]], set(), battle)
        saves = [event for event in events if event.kind == 'save' and event.result in ('success', 'fail')]
        self.assertTrue(saves)
        self.assertEqual(saves[0].result, 'success')
        self.assertEqual(victim.hp, 80 - 3)
        self.assertIn('половин', saves[0].text)

        ensure_recharge(dragon)
        consume_recharge(dragon, breath['name'])
        self.assertFalse(dragon.recharge_state[breath['name']]['ready'])
        dragon._rng = Scripted([6])
        notes = roll_recharges(dragon, 2)
        self.assertTrue(dragon.recharge_state[breath['name']]['ready'])
        self.assertEqual(notes[0].kind, 'recharge')
        self.assertEqual(notes[0].natural, 6)
        consume_recharge(dragon, breath['name'])
        dragon._rng = Scripted([2])
        roll_recharges(dragon, 3)
        self.assertFalse(dragon.recharge_state[breath['name']]['ready'])

    def test_psi_brawler_bonus_shove_parses_as_prone_save(self):
        monster = load('goblin-psi-brawler.html')
        shove = next(item for item in monster['bonus_actions']
                     if 'толчок' in item['name'].lower())
        effect = shove['effect']
        self.assertEqual(effect['ability'], 'str')
        self.assertEqual(effect['dc'], 13)
        self.assertEqual(effect['conditions'], ['prone'])
        self.assertEqual(effect['area'], 'single')
        self.assertEqual(effect['range_ft'], 30)

    def test_grapple_rider_from_fixture(self):
        monster = load('constrictor.html')
        bite = next(item for item in monster['attacks'] if item['name'] == 'Укус')
        self.assertEqual(bite['riders'][0]['condition'], 'grappled')
        self.assertEqual(bite['riders'][0]['escape_dc'], 16)
        self.assertIsNone(bite['riders'][0]['save'])
        snake = unit('Змея', 0, rng=Scripted([15, 4, 4]), attacks=[
            Attack('Укус', 6, 2, 'd6', 4, 'колющий', 10, riders=bite['riders'])])
        prey = unit('Добыча', 1, hp=40, speed=30)
        from combat_core import execute_strikes
        lines, killed = execute_strikes(snake, prey, snake.attacks, [[snake], [prey]], {}, None)
        self.assertFalse(killed)
        self.assertTrue(has_condition(prey, 'grappled'))
        self.assertEqual(effective_speed(prey), 0)
        self.assertEqual(prey.conditions[0]['duration'].get('escape_dc'), 16)
        self.assertTrue(any('схвачен' in line for line in lines))

    def test_unparsed_save_stays_text_with_warning(self):
        effect, warning = parse_special_effect(
            'Странность',
            'Все существа делают спасбросок удачи Сл 15 и происходит нечто.')
        self.assertIsNone(effect)
        self.assertIn('остаётся текстом', warning)

    def test_round_logs_save_and_skips_incapacitated(self):
        stunner = unit('Маг', 0, hp=20, rng=Scripted([12, 8, 4]))
        victim = unit('Страж', 1, hp=30, rng=Scripted([1]))
        apply_condition(victim, 'stunned')
        result = run_round([[stunner], [victim]], ['А', 'Б'], {}, None,
                           DecisionEngine(), auto_move=False, rng=Scripted([10, 1, 8, 1]))
        self.assertTrue(any(event.kind == 'condition' and event.result == 'skip'
                            for event in result.events))
        self.assertNotIn('Страж →', result.text)


class TestUndoAndLog(unittest.TestCase):

    def test_undo_restores_conditions_and_recharge(self):
        class Doc:
            def __init__(self):
                self.sides = []
                self.side_names = ['А', 'Б']
                self.ignore_sides = {}
                self.alliance_settings = []
                self.battle_map = None
                self.battle_events = []
                self.round_no = 1
                self.engine = DecisionEngine()
                self.setup = []
                self.selected = None

        left = unit('Рыцарь', 0)
        right = unit('Гоблин', 1)
        apply_condition(right, 'frightened', source=left, duration={
            'kind': 'rounds', 'whose': 'target', 'rounds': 3,
            'ability': 'wis', 'dc': 13})
        right.recharge_state = {'Дыхание': {'low': 5, 'high': 6, 'ready': False}}
        right.legendary_resistance = {'count': 3}
        right.legendary_resistance_remaining = 1
        doc = Doc()
        doc.sides = [[left], [right]]
        before = capture_battle(doc)
        remove = right.conditions[0]
        from conditions import remove_condition
        remove_condition(right, cond=remove, reason='проверка')
        right.recharge_state['Дыхание']['ready'] = True
        right.legendary_resistance_remaining = 3
        after = capture_battle(doc)
        history = BattleHistory()
        self.assertTrue(history.commit('состояние', before, after))
        restored = history.undo()
        apply_snapshot(restored, doc)
        again = doc.sides[1][0]
        self.assertTrue(has_condition(again, 'frightened'))
        self.assertEqual(again.conditions[0]['duration']['rounds'], 3)
        self.assertFalse(again.recharge_state['Дыхание']['ready'])
        self.assertEqual(again.legendary_resistance_remaining, 1)

    def test_log_filter_conditions_category(self):
        save = CombatEvent(kind='save', text='спасбросок Ловкости', result='fail',
                           natural=4, modifier=2, attack_total=6, dc=15)
        applied = CombatEvent(kind='condition', text='состояние «испуган»', result='applied',
                              condition='frightened')
        attack = CombatEvent(kind='attack', text='попадание', result='hit')
        self.assertTrue(event_visible(save, kind='conditions'))
        self.assertTrue(event_visible(applied, kind='conditions'))
        self.assertFalse(event_visible(attack, kind='conditions'))
        self.assertIn('Сл 15', '\n'.join(__import__('combat_log').detail_lines(save)))


class TestQtBadges(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def test_list_badge_and_menu_roundtrip_in_undo(self):
        from qt_app import MainWindow
        win = MainWindow()
        try:
            fighter = unit('Альфа', 0)
            foe = unit('Бета', 1)
            win.sides = [[fighter], [foe]]
            win.side_names = ['А', 'Б']
            win.battle_map = BattleMap(8, 8)
            win.battle_map.place(fighter, 0, 0)
            win.battle_map.place(foe, 2, 0)
            win.rebuild_battle_lists()
            win._current = capture_battle(win)
            win._history_ready = True
            win._impose(foe, 'frightened')
            self.assertIn('ИСП', win._enemy_text(foe))
            self.assertIn('испуган', win._enemy_tip(foe).lower())
            win.map_view.rebuild(win.battle_map, win.sides, foe)
            texts = [item.text() for item in win.map_view.scene().items()
                     if hasattr(item, 'text')]
            self.assertTrue(any('ИСП' in text for text in texts))
            win._lift(foe, foe.conditions[0])
            self.assertFalse(has_condition(foe, 'frightened'))
            win.do_undo()
            self.assertTrue(has_condition(win.sides[1][0], 'frightened'))
            labels = [win.log_panel.kind.itemText(i) for i in range(win.log_panel.kind.count())]
            self.assertIn('Состояния и спасброски', labels)
        finally:
            win.close()


if __name__ == '__main__':
    unittest.main()
