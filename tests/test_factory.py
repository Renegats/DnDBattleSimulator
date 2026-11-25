"""Юнит-тесты фабрики существ (factory.EnemyFactory.create_enemy) через DI-реестр.

Честная рамка: граф импортов фабрики
(factory->entities->observer/battle_strategies/random/typing/abc) не тянет GUI,
и фабрика тестировалась без интерфейса и до DI. Выигрыш DI-реестра
другой и конкретный:
  (1) подменяемый источник данных - логика фабрики (_make_attack/_finish/
      _apply_def/lookup) проверяется на крошечном фейковом реестре, а не на
      сотенной производственной литере CREATURE_DEFS;
  (2) изоляция тестов - каждый CreatureRegistry владеет СВОМИ словарями, поэтому
      регистрация типа в одном тесте не протекает в другой (утечка, которую
      общий глобальный EnemyFactory.CUSTOM_TYPES дать не может).

Вид test double = Fake-источник данных (реальный объект-реестр с фейковыми def,
построенными через модульный _creature_def => схема фейков идентична прод-лите).

Регресс-guard test_production_default_intact доказывает, что parameter injection
с дефолтом НЕ изменил поведение приложения: create_enemy без registry =>
PRODUCTION_REGISTRY => реальный гоблин из прод-литеры. Это же guard отвечает на
текущий вопрос про ошибку create_armies: если ЭТОТ тест зелёный, а создание армий
красное - корень НЕ в фабрике, а в сборке армий в интерфейсе (нужен трейсбек).
"""
import unittest

from factory import EnemyFactory, CreatureRegistry, PRODUCTION_REGISTRY, _creature_def


def melee(name='Атака', bonus=0, dice='d6', mod=0, dtype=''):
    return {'name': name, 'attack_bonus': bonus, 'damage_dice_count': 1,
            'damage_dice_type': dice, 'damage_modifier': mod, 'damage_type': dtype}


def bow(name='Короткий лук', bonus=4, dice='d6', mod=2, dtype='колющий', reach=80):
    return {'name': name, 'attack_bonus': bonus, 'damage_dice_count': 1,
            'damage_dice_type': dice, 'damage_modifier': mod,
            'damage_type': dtype, 'range_ft': reach}


def base_defs():
    return {'обычный': _creature_def(hp=10, ac=10, attacks=[melee()])}


class TestCreatureFactory(unittest.TestCase):

    def test_create_from_fake_registry_maps_schema_to_enemy(self):
        reg = CreatureRegistry(defs={
            'обычный': _creature_def(hp=10, ac=10, attacks=[melee()]),
            'тестгоблин': _creature_def(
                hp=7, ac=14, speed=30,
                attacks=[melee('Короткий меч', bonus=4, mod=2, dtype='рубящий'),
                         bow()],
                ability_scores={'str': 8, 'int': 10},
                multiattack=[{'attack': 'Когти', 'count': 2}]),
        })
        e = EnemyFactory.create_enemy('тестгоблин', 'Г', 0, registry=reg)
        self.assertEqual(e.hp, 7)
        self.assertEqual(e.ac, 14)
        self.assertEqual(e.speed, 30)
        self.assertEqual(len(e.attacks), 2)
        by_name = {a.name: a for a in e.attacks}
        self.assertEqual(by_name['Короткий лук'].range_ft, 80, '_make_attack сохранил range_ft')
        self.assertEqual(by_name['Короткий меч'].range_ft, 5, 'melee без range_ft => дефолт 5')
        self.assertEqual(e.ability_scores, {'str': 8, 'int': 10})
        self.assertEqual(e.multiattack, [{'attack': 'Когти', 'count': 2}])

    def test_unknown_type_falls_back_to_obychny(self):
        reg = CreatureRegistry(defs={
            'обычный': _creature_def(hp=10, ac=10, attacks=[melee()]),
            'гоблин': _creature_def(hp=7, ac=14, attacks=[melee()]),
        })
        e = EnemyFactory.create_enemy('дракон', 'Д', 0, registry=reg)
        self.assertEqual(e.hp, 10, 'fallback на обычный (hp=10), не краш')
        self.assertEqual(e.ac, 10)

    def test_custom_priority_over_defs(self):
        reg = CreatureRegistry(defs={'х': _creature_def(hp=1, ac=1, attacks=[melee()])})
        reg.register('х', hp=99, ac=5, attacks=[melee()], speed=30, regen=0,
                     multiattack=None, ability_scores={}, ability_mods={}, saves={},
                     skills={}, senses={}, vulnerabilities=[], resistances=[],
                     immunities=[], condition_immunities=[], languages=[],
                     cr=None, prof_bonus=None, size=None, type=None, traits=[])
        e = EnemyFactory.create_enemy('х', 'Х', 0, registry=reg)
        self.assertEqual(e.hp, 99, 'custom перекрывает defs (порядок lookup)')

    def test_registry_isolation_no_leak_between_registries(self):
        reg_a = CreatureRegistry(defs=base_defs())
        reg_b = CreatureRegistry(defs=base_defs())
        reg_a.register('мутант', hp=99, ac=5, attacks=[melee()], speed=30, regen=0,
                       multiattack=None, ability_scores={'int': 20}, ability_mods={},
                       saves={}, skills={}, senses={}, vulnerabilities=[],
                       resistances=[], immunities=[], condition_immunities=[],
                       languages=[], cr=None, prof_bonus=None, size=None,
                       type=None, traits=[])
        a = EnemyFactory.create_enemy('мутант', 'M', 0, registry=reg_a)
        b = EnemyFactory.create_enemy('мутант', 'M', 0, registry=reg_b)
        self.assertEqual(a.hp, 99, 'reg A видит свой custom')
        self.assertEqual(b.hp, 10, 'reg B НЕ видит custom reg A => fallback обычный (нет утечки)')
        self.assertNotIn('мутант', reg_b.custom)
        self.assertIn('мутант', reg_a.custom)

    def test_production_default_intact(self):
        e = EnemyFactory.create_enemy('гоблин', 'Г', 0)
        self.assertEqual(e.hp, 7, 'прод-литера цела: гоблин hp=7')
        self.assertEqual(e.ac, 14)
        by_name = {a.name: a for a in e.attacks}
        self.assertEqual(by_name['Короткий лук'].range_ft, 80)
        self.assertEqual(e.ability_scores.get('int'), 10)
        self.assertIsNone(e.multiattack, 'у прод-гоблина мультиатаки нет')
        self.assertIs(PRODUCTION_REGISTRY.defs, EnemyFactory.CREATURE_DEFS,
                      'PRODUCTION_REGISTRY оборачивает прод-литеру по ссылке')


if __name__ == '__main__':
    unittest.main(verbosity=2)