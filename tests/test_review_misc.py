"""Мелкие правки из ревью: средний урон, пустой арсенал, предупреждение фабрики,
дубли ключей, URL-кодирование поиска."""
import ast
import unittest
from pathlib import Path
from unittest import mock

import bestiary_core
from battle_strategies import AggressiveStrategy, damage_score
from entities import Attack, Enemy
from factory import CreatureRegistry, EnemyFactory, _creature_def


ROOT = Path(__file__).resolve().parents[1]


def melee(name='Атака'):
    return {'name': name, 'attack_bonus': 0, 'damage_dice_count': 1,
            'damage_dice_type': 'd6', 'damage_modifier': 0, 'damage_type': ''}


class TestDamageScoreAndStrategies(unittest.TestCase):

    def test_damage_score_uses_average_not_max(self):
        # 1d4+10: среднее 12.5, максимум 14. 2d8: среднее 9, максимум 16.
        # Старая формула count*sides+mod выбирала 2d8.
        modest = Attack('Скромная', 0, 1, 'd4', 10, '')
        flashy = Attack('Громкая', 0, 2, 'd8', 0, '')
        self.assertAlmostEqual(damage_score(modest), 12.5)
        self.assertAlmostEqual(damage_score(flashy), 9.0)
        self.assertGreater(damage_score(modest), damage_score(flashy))

    def test_aggressive_without_attacks_returns_none(self):
        empty = Enemy('Пустой', 5, 10, [], 0)
        empty.strategy = AggressiveStrategy()
        target = Enemy('Цель', 5, 10, [Attack('Удар', 0, 1, 'd6', 0)], 1)
        self.assertIsNone(empty.strategy.select_attack(empty, target))


class TestFactoryWarning(unittest.TestCase):

    def setUp(self):
        self.reg = CreatureRegistry(defs={
            'обычный': _creature_def(hp=10, ac=10, attacks=[melee()]),
        })

    def test_unknown_type_warns_and_falls_back(self):
        with self.assertLogs('factory', level='WARNING') as captured:
            enemy = EnemyFactory.create_enemy('нет такого', 'Х', 0, registry=self.reg)
        self.assertEqual(enemy.hp, 10)
        self.assertEqual(enemy.ac, 10)
        self.assertTrue(any('нет такого' in line for line in captured.output))

    def test_known_type_does_not_warn(self):
        with self.assertNoLogs('factory', level='WARNING'):
            enemy = EnemyFactory.create_enemy('обычный', 'Х', 0, registry=self.reg)
        self.assertEqual(enemy.hp, 10)


class TestBestiaryCleanup(unittest.TestCase):

    def test_importer_num_words_has_no_duplicate_keys(self):
        # Словарь остался один, в bestiary_core: Tk-импортёр больше не копирует его.
        tree = ast.parse((ROOT / 'bestiary_core.py').read_text(encoding='utf-8'))
        found = False
        for stmt in tree.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == 'NUM_WORDS' for t in stmt.targets):
                continue
            keys = [ast.literal_eval(key) for key in stmt.value.keys]
            found = True
            self.assertEqual(len(keys), len(set(keys)))
            values = dict(zip(keys, (ast.literal_eval(v) for v in stmt.value.values)))
            self.assertEqual(values['одним'], 1)
            self.assertEqual(values['две'], 2)
            self.assertEqual(values['два'], 2)
        self.assertTrue(found)
        importer = (ROOT / 'bestiary_importer.py').read_text(encoding='utf-8')
        self.assertIn('bestiary_core.parse_statblock', importer)
        self.assertNotIn('ATTACK_RE', importer)

    def test_search_query_is_passed_as_request_params(self):
        import tempfile
        bestiary_core._PAGES.clear()
        previous = bestiary_core.CACHE_DIR
        bestiary_core.CACHE_DIR = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: setattr(bestiary_core, 'CACHE_DIR', previous))
        seen = {}

        class Response:
            status_code = 200
            text = '<html></html>'
            encoding = 'utf-8'

        def fake_get(url, headers=None, timeout=None, params=None, **kwargs):
            seen['url'] = url
            seen['params'] = params
            return Response()

        with mock.patch.object(bestiary_core.requests, 'get', fake_get):
            html = bestiary_core.fetch_search('орк & маг')
        self.assertEqual(html, '<html></html>')
        self.assertEqual(seen['url'], 'https://dnd.su/bestiary/')
        self.assertEqual(seen['params'], {'search': 'орк & маг'})
        self.assertNotIn('орк', seen['url'])
        prepared = bestiary_core.requests.Request(
            'GET', seen['url'], params=seen['params']).prepare().url
        self.assertNotIn(' ', prepared)
        self.assertNotIn('орк & маг', prepared)

    def test_importer_search_uses_params(self):
        import bestiary_importer
        seen = {}

        class Response:
            status_code = 200
            text = 'ok'
            encoding = 'utf-8'

        def fake_get(url, headers=None, timeout=None, params=None, **kwargs):
            seen['url'] = url
            seen['params'] = params
            seen['headers'] = headers
            return Response()

        with mock.patch.object(bestiary_importer.requests, 'get', fake_get):
            response = bestiary_importer.fetch_search_page('древний красный', {'User-Agent': 'test'})
        self.assertEqual(response.text, 'ok')
        self.assertEqual(seen['url'], 'https://dnd.su/bestiary/')
        self.assertEqual(seen['params'], {'search': 'древний красный'})
        self.assertEqual(seen['headers'], {'User-Agent': 'test'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
