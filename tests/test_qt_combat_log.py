"""Журнал Qt и линии атак. Запускать с QT_QPA_PLATFORM=offscreen."""
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QFileDialog, QTreeView

from battle_map_model import BattleMap
from combat_log import CombatEvent, DamagePart
from entities import Attack, Enemy
from qt_app import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _fighter(name, side, hp=20, ac=14):
    enemy = Enemy(name, hp, ac, [Attack('Меч', 5, 1, 'd8', 3, 'рубящий')], side, speed=30)
    enemy.ability_scores = {'dex': 12, 'int': 10}
    enemy.ability_mods = {'dex': 1, 'int': 0}
    return enemy


class TestQtCombatLog(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def _window_with_pair(self):
        win = MainWindow()
        left = _fighter('Альфа', 0)
        right = _fighter('Бета', 1, hp=12, ac=12)
        win.sides = [[left], [right]]
        win.side_names = ['Алые', 'Синие']
        win.ignore_sides = {}
        win.battle_map = BattleMap(16, 8)
        win.battle_map.place(left, 0, 0)
        win.battle_map.place(right, 3, 0)
        win.log_panel.set_roster(win.sides, win.side_names)
        win.map_view.rebuild(win.battle_map, win.sides, None)
        return win, left, right

    def test_panel_filters_and_exports_without_rebuilding_text(self):
        win, left, right = self._window_with_pair()
        try:
            self.assertIsInstance(win.log_panel.view, QTreeView)
            win.run_round()
            self.assertGreater(win.round_no, 0)
            self.assertTrue(win.battle_events)
            self.assertGreater(win.log_panel.model.rowCount(), 0)
            attacks = [event for event in win.battle_events if event.kind == 'attack']
            self.assertTrue(attacks)
            self.assertTrue(win.map_view._attack_items)

            win.log_panel.set_kind('initiative')
            visible = win.log_panel.visible_events()
            self.assertTrue(visible)
            self.assertTrue(all(event.kind == 'initiative' for event in visible))

            win.log_panel.set_kind('all')
            win.log_panel.set_search('нет такой строки 999')
            self.assertEqual(win.log_panel.visible_events(), [])
            win.log_panel.set_search('')

            win.log_panel.proxy.creature_id = id(left)
            win.log_panel.proxy.invalidate()
            involved = win.log_panel.visible_events()
            self.assertTrue(involved)
            self.assertTrue(all(id(left) in (event.actor_id, event.target_id)
                                or any(roll.actor_id == id(left) for roll in event.rolls)
                                for event in involved))

            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, 'battle.json')
                with mock.patch.object(QFileDialog, 'getSaveFileName',
                                       return_value=(path, 'JSON (*.json)')):
                    win.export_log()
                self.assertTrue(os.path.isfile(path))
                self.assertIn('"events"', open(path, encoding='utf-8').read())
        finally:
            win.close()

    def test_selecting_entry_focuses_tokens_without_rebuilding_scene(self):
        win, left, right = self._window_with_pair()
        try:
            win.run_round()
            scene = win.map_view.scene()
            # Сначала убираем стрелки раунда, чтобы считать только сетку и токены.
            win.map_view.set_round_lines([])
            # Список держим живым: иначе сборщик может выбросить обёртки
            # QGraphicsItem, и следующий scene.items() получит другие id.
            base_items = list(scene.items())
            base_ids = {id(item) for item in base_items}
            spec = {'x1': 0, 'y1': 0, 'x2': 3, 'y2': 0, 'r1': 0.5, 'r2': 0.5, 'style': 'crit'}
            win.map_view.set_round_lines([spec])
            mid = len(scene.items())
            self.assertGreater(mid, len(base_ids))
            self.assertTrue(base_ids.issubset({id(item) for item in scene.items()}))
            win.map_view.set_round_lines([spec])
            # Повторная отрисовка заменяет стрелки и не плодит их.
            self.assertEqual(len(scene.items()), mid)
            self.assertTrue(base_ids.issubset({id(item) for item in scene.items()}))

            attack = next(event for event in win.battle_events if event.kind == 'attack')
            win.on_log_entry(attack)
            actor = left if attack.actor_id == id(left) else right
            self.assertIs(win.selected, actor)
            self.assertTrue(win.map_view._focus_items)
            self.assertTrue(win.map_view._focus_lines)
            self.assertTrue(base_ids.issubset({id(item) for item in scene.items()}))
            del base_items
        finally:
            win.close()

    def test_large_log_appends_in_batch(self):
        win = MainWindow()
        try:
            creatures = []
            for index in range(200):
                creatures.append(_fighter(f'Боец_{index}', index % 2))
            win.log_panel.set_roster([creatures[::2], creatures[1::2]], ['А', 'Б'])
            started = time.perf_counter()
            for round_no in range(1, 16):
                events = [CombatEvent(kind='round_start', round=round_no,
                                      text='=== НОВЫЙ РАУНД БОЯ ===')]
                for enemy in creatures:
                    events.append(CombatEvent(
                        kind='attack', round=round_no, result='hit',
                        actor=enemy.name, actor_id=id(enemy), actor_side=enemy.side,
                        target='Цель', action='Меч', natural=12, modifier=5,
                        attack_total=17, ac=14,
                        damages=[DamagePart('рубящий', 8, 8)],
                        hp_before=20, hp_after=12,
                        text=f'{enemy.name} → Цель (Меч: 17 vs AC 14) - ПОПАДАНИЕ! 8 урона'))
                win.log_panel.append_round(events)
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 2.5, f'журнал 200×15 собрался за {elapsed:.2f} с')
            self.assertEqual(win.log_panel.model.rowCount(), 15)
            win.log_panel.set_kind('hit')
            self.assertGreater(len(win.log_panel.visible_events()), 1000)
        finally:
            win.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
