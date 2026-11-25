"""Диалог пакетной симуляции. QT_QPA_PLATFORM=offscreen."""
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

import qt_async
from battle_map_model import BattleMap
from entities import Attack, Enemy
from qt_app import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _fighter(name, side, hp=24):
    enemy = Enemy(name, hp, 14, [Attack('Секира', 5, 1, 'd8', 3, 'рубящий')], side, speed=30)
    enemy.ability_scores = {'dex': 12, 'int': 10}
    enemy.ability_mods = {'dex': 1, 'int': 0}
    enemy.size = 'Средний'
    return enemy


def _wait(pred, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    return False


class TestQtBatch(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = _app()
        qt_async.install(cls._app)

    def _window(self):
        win = MainWindow()
        left = _fighter('Орк', 0)
        right = _fighter('Гоблин', 1, hp=18)
        win.sides = [[left], [right]]
        win.side_names = ['Орки', 'Гоблины']
        win.ignore_sides = {}
        win.battle_map = BattleMap(12, 8)
        win.battle_map.place(left, 0, 0)
        win.battle_map.place(right, 1, 0)
        return win, left, right

    def test_menu_and_button_open_dialog(self):
        win = MainWindow()
        try:
            menu = next(action.menu() for action in win.menuBar().actions()
                        if action.text() == 'Симуляция')
            self.assertEqual(menu.actions()[0].text(), 'Пакетная симуляция…')
            self.assertEqual(win.batch_btn.text(), 'Пакетная симуляция…')
            self.assertEqual(win.batch_btn.objectName(), 'batch_sim')
            with mock.patch.object(QMessageBox, 'warning') as warn:
                win.open_batch()
            self.assertTrue(warn.called)
            self.assertIsNone(win._batch_dialog)
        finally:
            win.close()

    def test_run_shows_table_and_exports_without_touching_the_battle(self):
        win, left, right = self._window()
        try:
            left.hp = 7
            win.open_batch()
            dialog = win._batch_dialog
            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.battles.value(), 1000)
            self.assertEqual(dialog.seed.value(), 1)
            self.assertEqual(dialog.rounds.value(), 40)
            dialog.battles.setValue(3)
            dialog.rounds.setValue(4)
            dialog.seed.setValue(4)
            dialog.start_btn.click()
            self.assertTrue(_wait(lambda: dialog._report is not None))
            report = dialog._report
            self.assertEqual(report.battles_done, 3)
            self.assertFalse(report.cancelled)
            self.assertEqual(dialog.side_table.rowCount(), 4)
            self.assertEqual(dialog.creature_table.rowCount(), 2)
            self.assertEqual(sum(count for _rounds, count in dialog.histogram._pairs), 3)
            self.assertIn('Боёв: 3', dialog.summary.text())
            self.assertEqual(left.hp, 7)
            self.assertEqual(right.hp, 18)
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, 'пакет.csv')
                with mock.patch.object(QFileDialog, 'getSaveFileName',
                                       return_value=(path, 'CSV (*.csv)')):
                    dialog.export_btn.click()
                with open(path, 'rb') as handle:
                    raw = handle.read()
            self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
            self.assertIn('номер;сид;победитель;раунды;исход;хиты_выживших',
                          raw.decode('utf-8-sig'))
        finally:
            if win._batch_dialog is not None:
                win._batch_dialog.close()
            win.close()

    def test_cancel_from_the_dialog(self):
        win, _left, _right = self._window()
        try:
            import monte_carlo
            real = monte_carlo.run_one

            def slow(*args, **kwargs):
                time.sleep(0.06)
                return real(*args, **kwargs)

            with mock.patch.object(monte_carlo, 'run_one', side_effect=slow):
                win.open_batch()
                dialog = win._batch_dialog
                dialog.battles.setValue(40)
                dialog.rounds.setValue(2)
                dialog.start_btn.click()
                self.assertTrue(_wait(lambda: dialog.progress.value() >= 1))
                dialog.cancel_btn.click()
                self.assertTrue(_wait(lambda: not dialog._running and dialog._report is not None))
            report = dialog._report
            self.assertTrue(report.cancelled)
            self.assertLess(report.battles_done, 40)
            self.assertGreaterEqual(report.battles_done, 1)
        finally:
            if win._batch_dialog is not None:
                win._batch_dialog.close()
            win.close()
