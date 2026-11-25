"""Qt: установка фонового насоса, режим крита, ручной шаг большого существа.

Запускать с QT_QPA_PLATFORM=offscreen (выставляется здесь до создания приложения).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QFileDialog

import qt_async
import qt_app
from battle_map_model import BattleMap
from entities import Attack, Enemy
from qt_app import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


class TestQtEntryAndCritMode(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def test_direct_main_installs_async_pump(self):
        installed = []

        def spy(app):
            installed.append(app)
            return app

        class App:
            def __init__(self, argv=None):
                self.argv = argv

            def exec(self):
                return 0

        class Win:
            def showMaximized(self):
                pass

        with mock.patch.object(qt_async, 'install', spy), \
                mock.patch.object(qt_app, 'QApplication', App), \
                mock.patch.object(qt_app, 'MainWindow', Win):
            with self.assertRaises(SystemExit):
                qt_app.main()
        self.assertEqual(len(installed), 1)
        self.assertIsInstance(installed[0], App)

    def test_crit_mode_defaults_to_double_all_and_roundtrips(self):
        win = MainWindow()
        try:
            self.assertEqual(win.crit_mode.currentData(), 'double_all')
            self.assertEqual(win.crit_mode.currentText(), 'Удваивать весь урон')
            labels = [win.crit_mode.itemText(i) for i in range(win.crit_mode.count())]
            self.assertEqual(labels, ['Удваивать весь урон', 'Удваивать только кости'])

            win.crit_mode.setCurrentIndex(win.crit_mode.findData('dice_only'))
            with tempfile.TemporaryDirectory() as tmp:
                previous = os.getcwd()
                os.chdir(tmp)
                try:
                    win.save_settings()
                    saved = next(Path(tmp, 'battle_settings').glob('*.json'))
                    data = json.loads(saved.read_text(encoding='utf-8'))
                    self.assertEqual(data['crit_mode'], 'dice_only')

                    old = dict(data)
                    old.pop('crit_mode')
                    old_path = Path(tmp, 'battle_settings', 'old.json')
                    old_path.write_text(json.dumps(old), encoding='utf-8')

                    with mock.patch.object(QFileDialog, 'getOpenFileName',
                                           return_value=(str(old_path), '')):
                        win.load_settings()
                    self.assertEqual(win.crit_mode.currentData(), 'double_all')

                    with mock.patch.object(QFileDialog, 'getOpenFileName',
                                           return_value=(str(saved), '')):
                        win.load_settings()
                    self.assertEqual(win.crit_mode.currentData(), 'dice_only')
                finally:
                    os.chdir(previous)
        finally:
            win.close()

    def test_manual_move_of_large_creature_rejects_overlap(self):
        win = MainWindow()
        try:
            big = Enemy('Огр', 30, 12, [Attack('Дубина', 5, 1, 'd8', 3, 'дробящий')],
                        0, speed=30)
            big.size = 'Большой'
            other = Enemy('Гоблин', 7, 14, [Attack('Меч', 4, 1, 'd6', 2, 'рубящий')],
                          1, speed=30)
            other.size = 'Средний'
            win.battle_map = BattleMap(12, 8)
            win.sides = [[big], [other]]
            win.battle_map.place(big, 0, 0)
            win.battle_map.place(other, 2, 0)
            win.selected = big
            win.on_cell(1, 0)
            self.assertEqual(win.battle_map.get_pos(big), (0, 0))
            win.on_cell(0, 2)
            self.assertEqual(win.battle_map.get_pos(big), (0, 2))
        finally:
            win.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
