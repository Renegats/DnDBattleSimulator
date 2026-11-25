"""Офлайн-разбор реальных карточек dnd.su и применение урона/легендарных действий.

Фикстуры — фрагмент живой страницы (карточка статблока), снятый 2026-11-25.
MM24 («Бросок рукопашной атаки») живёт на next.dnd.su; ссылка стоит на карточке
dnd.su плашкой MM24. Поиск по-прежнему ходит на dnd.su.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import bestiary_core
from bestiary_core import parse_statblock
from combat_core import execute_strikes, legendary_after_turn
from entities import Attack, Enemy
from factory import EnemyFactory

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def load(name):
    return parse_statblock((FIXTURES / name).read_text(encoding='utf-8'),
                           f'https://dnd.su/bestiary/{name}')


def attack_named(monster, name):
    for attack in monster['attacks']:
        if attack['name'] == name:
            return attack
    raise AssertionError(f'{name} нет среди {[a["name"] for a in monster["attacks"]]}')


class TestFixtures(unittest.TestCase):

    def test_troll_multiattack_keeps_bite_and_both_claws(self):
        monster = load('troll.html')
        self.assertEqual(monster['name'], 'Тролль')
        self.assertEqual(monster['hp'], 84)
        self.assertEqual(monster['ac'], 15)
        self.assertEqual(monster['regen'], 10)
        self.assertEqual(monster['size'], 'Большой')
        self.assertEqual(monster['multiattack'], [
            {'attack': 'Укус', 'count': 1},
            {'attack': 'Коготь', 'count': 2},
        ])
        bite = attack_named(monster, 'Укус')
        claw = attack_named(monster, 'Коготь')
        self.assertEqual((bite['damage_dice_count'], bite['damage_dice_type'], bite['damage_modifier']),
                         (1, 'd6', 4))
        self.assertEqual(bite['damage_type'], 'колющий')
        self.assertEqual(claw['damage_dice_count'], 2)
        self.assertEqual(claw['damage_type'], 'рубящий')
        self.assertNotIn('атаки не распознаны', monster['warnings'])
        self.assertNotIn('мультиатака распознана частично', monster['warnings'])
        self.assertFalse(monster['errors'])

    def test_goblin_two_weapons_and_no_stub(self):
        monster = load('goblin.html')
        self.assertEqual(monster['hp'], 7)
        self.assertEqual(monster['ac'], 15)
        self.assertEqual(monster['cr'], '1/4')
        self.assertEqual(monster['skills'].get('Скрытность'), '+6')
        self.assertIsNone(monster['multiattack'])
        sword = attack_named(monster, 'Скимитар')
        bow = attack_named(monster, 'Короткий лук')
        self.assertEqual(sword['attack_bonus'], 4)
        self.assertEqual(sword['range_ft'], 5)
        self.assertEqual(bow['range_ft'], 80)
        self.assertEqual(bow['damage_type'], 'колющий')
        self.assertNotEqual(monster['attacks'][0]['name'], 'Атака')

    def test_amethyst_dragon_claws_and_force_damage(self):
        monster = load('adult-amethyst-dragon.html')
        self.assertEqual(monster['name'], 'Взрослый аметистовый дракон')
        self.assertEqual(monster['hp'], 229)
        self.assertEqual(monster['ac'], 19)
        self.assertEqual(monster['speed'], 40)
        self.assertEqual(monster['multiattack'], [
            {'attack': 'Укус', 'count': 1},
            {'attack': 'Коготь', 'count': 2},
        ])
        bite = attack_named(monster, 'Укус')
        self.assertEqual(bite['damage_dice_type'], 'd10')
        self.assertEqual(bite['extra_damage'], [
            {'dice_count': 2, 'dice_type': 'd8', 'modifier': 0, 'damage_type': 'силовое поле'},
        ])
        self.assertIn('силовое поле', monster['resistances'])
        self.assertIn('психическая энергия', monster['resistances'])
        self.assertEqual(monster['legendary_resistance']['count'], 3)
        self.assertEqual(monster['legendary_actions']['per_round'], 3)
        usable = [item['name'] for item in monster['legendary_actions']['options'] if item['usable']]
        self.assertIn('Коготь', usable)
        self.assertGreaterEqual(len(monster['lair_actions']['actions']), 1)
        self.assertNotIn('мультиатака распознана частично', monster['warnings'])

    def test_psi_brawler_is_not_replaced_by_stub(self):
        monster = load('goblin-psi-brawler.html')
        self.assertEqual(monster['name'], 'Гоблин пси-драчун')
        self.assertEqual(monster['hp'], 31)
        self.assertEqual(monster['multiattack'], [{'attack': 'Безоружный удар', 'count': 2}])
        punch = attack_named(monster, 'Безоружный удар')
        self.assertEqual(punch['attack_bonus'], 5)
        self.assertEqual(punch['damage_dice_type'], 'd4')
        self.assertEqual(punch['damage_type'], 'дробящий')
        self.assertEqual(punch['extra_damage'][0]['damage_type'], 'психическая энергия')
        self.assertEqual(punch['extra_damage'][0]['dice_type'], 'd6')
        self.assertIn('психическая энергия', monster['resistances'])
        self.assertNotIn('атаки не распознаны', monster['warnings'])
        self.assertEqual(monster['errors'], [])

    def test_ancient_red_legendary_actions_and_fire(self):
        monster = load('ancient-red-dragon.html')
        self.assertEqual(monster['hp'], 546)
        self.assertEqual(monster['ac'], 22)
        self.assertEqual(monster['speed'], 40)
        self.assertEqual(monster['size'], 'Громадный')
        self.assertIn('огонь', monster['immunities'])
        self.assertEqual(monster['multiattack'], [
            {'attack': 'Укус', 'count': 1},
            {'attack': 'Коготь', 'count': 2},
        ])
        bite = attack_named(monster, 'Укус')
        self.assertEqual(bite['extra_damage'][0],
                         {'dice_count': 4, 'dice_type': 'd6', 'modifier': 0, 'damage_type': 'огонь'})
        self.assertEqual(attack_named(monster, 'Хвост')['range_ft'], 20)
        legendary = monster['legendary_actions']
        self.assertEqual(legendary['per_round'], 3)
        by_name = {item['name']: item for item in legendary['options']}
        self.assertEqual(by_name['Атака хвостом']['cost'], 1)
        self.assertEqual(by_name['Атака хвостом']['attack'], 'Хвост')
        self.assertTrue(by_name['Атака хвостом']['usable'])
        self.assertEqual(by_name['Атака крыльями']['cost'], 2)
        self.assertFalse(by_name['Атака крыльями']['usable'])
        self.assertEqual(monster['legendary_resistance']['count'], 3)
        self.assertEqual(len(monster['lair_actions']['actions']), 3)
        names = {item['name'] for item in monster['special_actions']}
        self.assertIn('Огненное дыхание (перезарядка 5–6)', names)

    def test_mage_dagger_is_melee_or_thrown(self):
        monster = load('mage.html')
        self.assertEqual(monster['cr'], '6')
        dagger = attack_named(monster, 'Кинжал')
        self.assertEqual(dagger['attack_bonus'], 5)
        self.assertEqual((dagger['damage_dice_count'], dagger['damage_dice_type'], dagger['damage_modifier']),
                         (1, 'd4', 2))
        self.assertEqual(dagger['range_ft'], 20)
        self.assertEqual(dagger['damage_type'], 'колющий')
        self.assertTrue(any('заклинаний' in trait['name'].lower() for trait in monster['traits']))

    def test_lich_spell_attack_and_legendary_cost(self):
        monster = load('lich.html')
        touch = attack_named(monster, 'Парализующее касание')
        self.assertEqual(touch['attack_bonus'], 12)
        self.assertEqual(touch['damage_dice_type'], 'd6')
        self.assertEqual(touch['damage_dice_count'], 3)
        self.assertEqual(touch['damage_type'], 'холод')
        self.assertTrue(touch['magical'])
        self.assertTrue(any('немагическ' in item for item in monster['immunities']))
        option = next(item for item in monster['legendary_actions']['options']
                      if item['name'] == 'Парализующее касание')
        self.assertEqual(option['cost'], 2)
        self.assertTrue(option['usable'])
        self.assertEqual(option['attack'], 'Парализующее касание')

    def test_2024_troll_attack_roll_wording(self):
        monster = load('troll-2024.html')
        self.assertEqual(monster['name'], 'Тролль')
        self.assertEqual(monster['hp'], 94)
        self.assertEqual(monster['ac'], 15)
        self.assertEqual(monster['regen'], 15)
        rend = attack_named(monster, 'Раздирание')
        self.assertEqual(rend['attack_bonus'], 7)
        self.assertEqual(rend['range_ft'], 10)
        self.assertEqual((rend['damage_dice_count'], rend['damage_dice_type'], rend['damage_modifier']),
                         (2, 'd6', 4))
        self.assertEqual(rend['damage_type'], 'рубящий')
        self.assertEqual(monster['multiattack'], [{'attack': 'Раздирание', 'count': 3}])
        self.assertNotIn('атаки не распознаны', monster['warnings'])


class TestParserEdges(unittest.TestCase):

    def test_plain_brosok_ataki_and_conditional_extra(self):
        html = '''
        <ul class="params card__article-body">
          <li class="size-type-alignment">Средний зверь</li>
          <li><strong>Класс Доспеха</strong> 13</li>
          <li><strong>Хиты</strong> <span data-type="middle">22</span></li>
          <li><strong>Скорость</strong> 30 футов</li>
          <li class="abilities">
            <div class="stat">Сил 10 (+0)</div><div class="stat">Лов 10 (+0)</div>
            <div class="stat">Тел 10 (+0)</div><div class="stat">Инт 10 (+0)</div>
            <div class="stat">Мдр 10 (+0)</div><div class="stat">Хар 10 (+0)</div>
          </li>
          <li class="subsection"><h3>Действия</h3><div>
            <p>Удар. Бросок атаки: +4, досягаемость 5 футов. Попадание: 6 (1к6+3) дробящего урона плюс 3 (1к6) урона огнём, если атака совершалась с преимуществом.</p>
            <p>Луч. Дальнобойная атака заклинанием: +5 к попаданию, дистанция 120 футов. Попадание: 7 (2к6) урона огнём.</p>
          </div></li>
        </ul>
        '''
        monster = parse_statblock(html)
        strike = attack_named(monster, 'Удар')
        self.assertEqual(strike['attack_bonus'], 4)
        self.assertEqual(strike['damage_type'], 'дробящий')
        self.assertNotIn('extra_damage', strike)
        self.assertIn('условный дополнительный урон не импортирован', monster['warnings'])
        bolt = attack_named(monster, 'Луч')
        self.assertTrue(bolt['magical'])
        self.assertEqual(bolt['range_ft'], 120)
        self.assertEqual(bolt['damage_type'], 'огонь')

    def test_empty_page_reports_errors_and_does_not_invent_an_attack(self):
        monster = parse_statblock('<html><body><p>пусто</p></body></html>')
        self.assertEqual(monster['attacks'], [])
        self.assertTrue(monster['warnings'])
        self.assertIn('атаки не распознаны', monster['warnings'])
        self.assertIn('карточка статблока не найдена, разбор по тексту страницы', monster['warnings'])
        self.assertTrue(any('хиты не распознаны' == item or 'хиты не распознаны' in item
                            for item in monster['warnings']))

    def test_characteristics_error_is_recorded(self):
        from statblock_parser import parse_characteristics
        out = parse_characteristics(None, None)
        self.assertTrue(out.get('errors'))


class ScriptedRng:
    def __init__(self, rolls):
        self._rolls = list(rolls)
        self._i = 0

    def randint(self, a, b):
        value = self._rolls[self._i]
        self._i += 1
        return value


class TestExtraDamageAndLegendary(unittest.TestCase):

    def test_extra_damage_respects_immunity(self):
        weapon = Attack('Укус', 5, 1, 'd6', 0, 'колющий', 5, False,
                        extra_damage=[{'dice_count': 1, 'dice_type': 'd6', 'modifier': 0,
                                       'damage_type': 'огонь'}])
        attacker = Enemy('Дракон', 50, 15, [weapon], 0, rng=ScriptedRng([15, 4, 6]))
        target = Enemy('Тролль', 40, 10, [], 1)
        target.immunities = ['огонь']
        lines, killed = execute_strikes(attacker, target, [weapon], [[attacker], [target]], {}, None)
        self.assertFalse(killed)
        self.assertEqual(target.hp, 36)  # 4 piercing, fire 6 -> 0
        self.assertTrue(any('иммунитет: огонь' in line for line in lines))

    def test_legendary_tail_after_another_turn(self):
        goblin = Enemy('Гоблин', 20, 10, [Attack('Кинжал', 4, 1, 'd4', 2, 'колющий')], 0,
                       rng=ScriptedRng([10, 2]))
        tail = Attack('Хвост', 8, 1, 'd8', 4, 'дробящий', 10)
        dragon = Enemy('Дракон', 80, 18, [tail], 1, rng=ScriptedRng([18, 5]))
        dragon.legendary_actions = {
            'per_round': 3,
            'options': [
                {'name': 'Обнаружение', 'cost': 1, 'desc': 'проверка', 'attack': None,
                 'count': 1, 'usable': False},
                {'name': 'Атака хвостом', 'cost': 1, 'desc': 'атака хвостом', 'attack': 'Хвост',
                 'count': 1, 'usable': True},
            ],
        }
        lines = legendary_after_turn(goblin, [[goblin], [dragon]], {}, None)
        self.assertTrue(any('легендарное действие' in line and 'Атака хвостом' in line for line in lines))
        self.assertEqual(dragon.legendary_remaining, 2)
        self.assertLess(goblin.hp, 20)
        # свой ход легендарку не тратит
        own = legendary_after_turn(dragon, [[goblin], [dragon]], {}, None)
        self.assertEqual(own, [])

    def test_run_round_logs_legendary_action(self):
        from battle_round import run_round
        from decision_engine import DecisionEngine
        goblin = Enemy('Гоблин', 30, 8, [Attack('Кинжал', 2, 1, 'd4', 1, 'колющий')], 0)
        tail = Attack('Хвост', 6, 1, 'd8', 3, 'дробящий', 10)
        dragon = Enemy('Дракон', 90, 18, [tail], 1)
        dragon.legendary_actions = {
            'per_round': 1,
            'options': [{'name': 'Атака хвостом', 'cost': 1, 'desc': 'хвост',
                         'attack': 'Хвост', 'count': 1, 'usable': True}],
        }
        _outcome, log = run_round([[goblin], [dragon]], ['А', 'Б'], {}, None,
                                  DecisionEngine(), auto_move=False, rng=ScriptedRng([1, 1, 1, 1]))
        self.assertIn('легендарное действие', log)
        self.assertIn('Атака хвостом', log)

    def test_factory_keeps_extra_damage_and_legendary(self):
        monster = load('ancient-red-dragon.html')
        EnemyFactory.register_type(
            'тест-дракон', hp=monster['hp'], ac=monster['ac'], attacks=monster['attacks'],
            speed=monster['speed'], regen=0, multiattack=monster['multiattack'],
            legendary_actions=monster['legendary_actions'],
            immunities=monster['immunities'])
        enemy = EnemyFactory.create_enemy('тест-дракон', 'Д', 0)
        bite = next(attack for attack in enemy.attacks if attack.name == 'Укус')
        self.assertEqual(bite.extra_damage[0]['damage_type'], 'огонь')
        self.assertEqual(enemy.legendary_actions['per_round'], 3)
        self.assertEqual(enemy.multiattack[0]['attack'], 'Укус')
        restored = Enemy.from_dict(enemy.to_dict())
        self.assertEqual(restored.legendary_actions['options'][1]['attack'], 'Хвост')
        self.assertEqual(restored.attacks[0].extra_damage[0]['dice_count'], 4)


class TestNetwork(unittest.TestCase):

    def test_retries_transient_errors_then_succeeds(self):
        calls = {'n': 0}

        class Response:
            def __init__(self, code, text='ok'):
                self.status_code = code
                self.text = text
                self.encoding = 'utf-8'

        def fake_get(url, headers=None, timeout=None, params=None, **kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                raise bestiary_core.requests.ConnectionError('reset')
            if calls['n'] == 2:
                return Response(503)
            return Response(200, 'page')

        with mock.patch.object(bestiary_core.requests, 'get', fake_get), \
                mock.patch.object(bestiary_core.time, 'sleep') as slept:
            text = bestiary_core.fetch('https://dnd.su/bestiary/1-x/', attempts=3)
        self.assertEqual(text, 'page')
        self.assertEqual(calls['n'], 3)
        self.assertEqual(slept.call_count, 2)

    def test_disk_cache_skips_second_request(self):
        previous = bestiary_core.CACHE_DIR
        bestiary_core.CACHE_DIR = Path(tempfile.mkdtemp())
        bestiary_core._PAGES.clear()
        calls = {'n': 0}

        class Response:
            status_code = 200
            text = '<html>cached-body</html>'
            encoding = 'utf-8'

        def fake_get(*args, **kwargs):
            calls['n'] += 1
            return Response()

        try:
            with mock.patch.object(bestiary_core.requests, 'get', fake_get):
                first = bestiary_core.fetch_cached('https://dnd.su/bestiary/9-cache/')
                bestiary_core._PAGES.clear()
                second = bestiary_core.fetch_cached('https://dnd.su/bestiary/9-cache/')
            self.assertEqual(first, second)
            self.assertEqual(calls['n'], 1)
            self.assertTrue(any(bestiary_core.CACHE_DIR.glob('*.html')))
        finally:
            bestiary_core.CACHE_DIR = previous
            bestiary_core._PAGES.clear()


class TestPreviewWarnings(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def test_dialog_shows_warnings_and_keeps_import_enabled(self):
        from PyQt6.QtWidgets import QLabel
        from qt_bestiary import BestiaryDialog
        dialog = BestiaryDialog()
        monster = {
            'name': 'Пустышка', 'hp': 10, 'ac': 12, 'speed': 30, 'regen': 0,
            'attacks': [], 'warnings': ['атаки не распознаны'], 'errors': [],
            'ability_scores': {}, 'ability_mods': {}, 'portraits': [],
            'multiattack': None, 'traits': [], 'size': 'Средний', 'type': 'зверь',
        }
        dialog._got_block(monster, dialog._req)
        label = dialog.findChild(QLabel, 'importWarnings')
        self.assertIsNotNone(label)
        self.assertIn('атаки не распознаны', label.text())
        self.assertTrue(dialog.btn_import.isEnabled())
        dialog.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
