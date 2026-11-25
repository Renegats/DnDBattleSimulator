"""Юнит-тесты слоя принятия решений (decision_engine.DecisionEngine.decide).

Плод DI шага 1 + разделения слоёв: decide() проверяется БЕЗ tkinter, БЕЗ
battle_map, БЕЗ бросков кубиков. Граф импортов: unittest -> decision_engine ->
battle_strategies(abc, random). Ни один узел не тянет tkinter => тест изолирован
от GUI. Достижимость цели живёт ЕДИНСТВЕННЫМ владельцем в _pick_target архетипа
(tier1/2/speed) - A1 из decide удалён, чтобы две оси не дрались за выбор цели.

Вид test double = Fake (реальные данные состояния: pos/attacks/int/hp/ac),
а не Mock: decide читает СОСТОЯНИЕ юнитов и зовёт только strategy.select_target
(настоящая AggressiveStrategy => детерминированно, без random).
"""
import unittest
from types import SimpleNamespace

from decision_engine import DecisionEngine, tier_from_int
from battle_strategies import AggressiveStrategy


def make_attack(name, *, bonus=4, dice='d6', count=1, mod=2,
                dtype='рубящий', reach=5):
    return SimpleNamespace(
        name=name, attack_bonus=bonus, damage_dice_count=count,
        damage_dice_type=dice, damage_modifier=mod, damage_type=dtype,
        range_ft=reach,
    )


def make_enemy(name, side, *, hp, ac, attacks, int_score, pos,
               immunities=(), resistances=(), vulnerabilities=(),
               multiattack=None, speed=30):
    e = SimpleNamespace(
        name=name, side=side, alive=True, hp=hp, max_hp=hp, ac=ac,
        attacks=attacks, ability_scores={'int': int_score},
        immunities=list(immunities), resistances=list(resistances),
        vulnerabilities=list(vulnerabilities),
        multiattack=multiattack, speed=speed, pos=pos,
        ignore_sides=set(), moved_ft=0,
    )
    e.strategy = AggressiveStrategy()
    return e


class TestDecisionEngine(unittest.TestCase):

    def setUp(self):
        self.engine = DecisionEngine()   # DI: движок напрямую, без GUI

    def test_goblin_archer_holds_distance_and_bow_beats_sword(self):
        goblin = make_enemy('Гоблин', 0, hp=7, ac=15, int_score=9, pos=(0, 0),
                            attacks=[make_attack('Меч', dtype='рубящий', reach=5),
                                     make_attack('Короткий лук', dtype='колющий', reach=80)])
        skeleton = make_enemy('Скелет', 1, hp=13, ac=12, int_score=6, pos=(7, 0),
                              attacks=[make_attack('Короткий меч', reach=5)])
        decision = self.engine.decide(goblin, [[goblin], [skeleton]], set())
        self.assertEqual(decision.tier, 2, 'INT=9 => Tier 2 (Тактический)')
        self.assertEqual(decision.attack.name, 'Короткий лук',
                         'B1: меч reach=5 отсечён на дистанции 35 фт')
        self.assertEqual(decision.move_intent, 'hold',
                         'C2-half: лук достаёт, враг опасен в melee => держим дистанцию')
        self.assertIn('держит дистанцию', decision.rationale)
        self.assertEqual(decision.target.name, 'Скелет')
        snap = self.engine.get_round_log()[-1]
        cand = {c['name']: c for c in snap['candidates']}
        self.assertIn('[B1]', cand['Меч']['reject'], 'меч отсечён по дальности [B1]')
        self.assertTrue(cand['Короткий лук'].get('chosen'), 'лук выбран как лучший в пуле')

    def test_full_immunity_with_no_alternative_still_attacks_gracefully(self):
        goblin = make_enemy('Гоблин-дубинщик', 0, hp=7, ac=15, int_score=9, pos=(0, 0),
                            attacks=[make_attack('Дубина', dtype='дробящий', reach=5)])
        demon = make_enemy('Демон', 1, hp=50, ac=18, int_score=15, pos=(1, 0),
                           attacks=[make_attack('Коготь', reach=5)],
                           immunities=['дробящий'])
        decision = self.engine.decide(goblin, [[goblin], [demon]], set())
        self.assertEqual(decision.target.name, 'Демон',
                         'A5: альтернатив нет => бьём иммунного (выбора нет), не краш')
        self.assertEqual(decision.attack.name, 'Дубина',
                         'B2: атака всё равно выбрана (eff=0), урон обнулится позднее')
        self.assertIn('иммунен', decision.rationale)

    def test_melee_only_unit_approaches_instead_of_stalling(self):
        fighter = make_enemy('Воин', 0, hp=10, ac=16, int_score=10, pos=(0, 0),
                             attacks=[make_attack('Меч', reach=5)])
        foe = make_enemy('Враг', 1, hp=10, ac=12, int_score=10, pos=(7, 0),
                         attacks=[make_attack('Меч', reach=5)])
        decision = self.engine.decide(fighter, [[fighter], [foe]], set())
        self.assertEqual(decision.attack.name, 'Меч', 'единственная атака выбрана')
        self.assertEqual(decision.move_intent, 'approach',
                         'C1: цели не достаём => подходим, а не стоим')
        self.assertEqual(decision.target_dist_ft, 5, 'reach меча = 5 фт (цель для подхода)')

    def test_tier_from_int_scale_and_graceful_default(self):
        self.assertEqual(tier_from_int(1), 0)
        self.assertEqual(tier_from_int(6), 1)
        self.assertEqual(tier_from_int(9), 2)
        self.assertEqual(tier_from_int(20), 4)
        self.assertEqual(tier_from_int(None), 2)   # недописанный Arcana-монстр => не овощ


if __name__ == '__main__':
    unittest.main(verbosity=2)