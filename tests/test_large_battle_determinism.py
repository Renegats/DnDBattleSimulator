"""Оптимизации линии обзора не меняют бой с фиксированным seed.

Отпечатки сняты до кэша и быстрого обхода клеток (seed 20261126).
"""
import hashlib
import json
import unittest

from tools.bench_large_battle import battle_fingerprint, run_once


EXPECTED = {
    (60, False): '97190aff93bf287d207318ca92c9a9d32d80b3972b1fe2ca0500fba2c358892b',
    (60, True): '48e63f054a4622bd2f12ff867197130083a1dd7fc9abc477f93d523a6387a64d',
    (100, False): 'e91901815d3379f8e906796331d661a1b67013b8af504a2a95670ff153a14299',
    (100, True): '22dc148a552fbb4efe47b6a88a211548b88e51f18381cb4b2c1691b855e80ef8',
    (150, False): '4a1315498b984673dbdcc8fc51a067740a3cf83b7a0cbe14a591f747bbb0e5b8',
    (150, True): 'aec10718e0abbc1b9a74a7310ab8e65394b2686258b2b7270b5bd44e5a974e19',
}


class TestLargeBattleDeterminism(unittest.TestCase):

    def test_fingerprints_match_pre_optimization_rounds(self):
        for (count, terrain), expect in EXPECTED.items():
            with self.subTest(count=count, terrain=terrain):
                sides, _names, _battle_map, result = run_once(count, terrain)
                fingerprint = battle_fingerprint(sides, result.events)
                digest = hashlib.sha256(
                    json.dumps(fingerprint, ensure_ascii=False, default=str).encode('utf-8')
                ).hexdigest()
                self.assertEqual(digest, expect)
                again, _names2, _map2, result2 = run_once(count, terrain)
                digest2 = hashlib.sha256(json.dumps(
                    battle_fingerprint(again, result2.events),
                    ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
                self.assertEqual(digest2, digest)


if __name__ == '__main__':
    unittest.main()
