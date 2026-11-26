"""Undo/redo в окне Qt. Запускать с QT_QPA_PLATFORM=offscreen."""
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import Qt, QEvent, QPointF
from PyQt6.QtGui import QKeySequence, QMouseEvent
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from battle_history import capture_battle
from battle_map_model import BattleMap
from entities import Attack, Enemy
from factory import EnemyFactory
from qt_app import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _fighter(name, side, hp=30, speed=30):
    enemy = Enemy(name, hp, 14, [Attack('Секира', 5, 1, 'd12', 3, 'рубящий')], side, speed=speed)
    enemy.ability_scores = {'dex': 12, 'int': 10}
    enemy.ability_mods = {'dex': 1, 'int': 0}
    enemy.size = 'Средний'
    return enemy


def _baseline(win):
    win.history.clear()
    win._current = capture_battle(win)
    win._sync_history_actions()


def _press(view, kind, pos):
    event = QMouseEvent(
        kind, QPointF(pos), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    if kind == QEvent.Type.MouseButtonPress:
        view.mousePressEvent(event)
    elif kind == QEvent.Type.MouseMove:
        view.mouseMoveEvent(event)
    else:
        view.mouseReleaseEvent(event)


class TestQtUndo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def setUp(self):
        self._types = json.loads(json.dumps(EnemyFactory.CUSTOM_TYPES))

    def tearDown(self):
        EnemyFactory.CUSTOM_TYPES.clear()
        EnemyFactory.CUSTOM_TYPES.update(self._types)

    def _window(self):
        win = MainWindow()
        left = _fighter('Орк 3', 0)
        right = _fighter('Эльф 1', 1, hp=20)
        win.sides = [[left], [right]]
        win.side_names = ['Орки', 'Эльфы']
        win.ignore_sides = {}
        win.battle_map = BattleMap(16, 8)
        win.battle_map.place(left, 0, 0)
        win.battle_map.place(right, 1, 0)
        win.log_panel.set_roster(win.sides, win.side_names)
        win.map_view.rebuild(win.battle_map, win.sides, None)
        _baseline(win)
        return win, left, right

    def test_actions_start_disabled_and_name_the_step(self):
        win, left, _right = self._window()
        try:
            self.assertFalse(win.undo_action.isEnabled())
            self.assertFalse(win.redo_action.isEnabled())
            self.assertFalse(win.btn_undo.isEnabled())
            self.assertEqual(win.undo_action.shortcut(), QKeySequence('Ctrl+Z'))
            shortcuts = win.redo_action.shortcuts()
            self.assertIn(QKeySequence('Ctrl+Shift+Z'), shortcuts)
            self.assertIn(QKeySequence('Ctrl+Y'), shortcuts)
            menu = next(action.menu() for action in win.menuBar().actions()
                        if action.text() == 'Правка')
            self.assertEqual([action.objectName() for action in menu.actions()],
                             ['undo', 'redo'])
            self.assertEqual(win.btn_undo.toolTip(), 'Нечего отменять')

            win.selected = left
            win.on_cell(0, 2)
            self.assertEqual(win.battle_map.get_pos(left), (0, 2))
            self.assertTrue(win.undo_action.isEnabled())
            self.assertEqual(win.undo_action.text(), 'Отменить: ход Орк 3')
            self.assertEqual(win.btn_undo.toolTip(), 'Отменить: ход Орк 3')
            self.assertFalse(win.redo_action.isEnabled())

            win.show()
            win.map_view.setFocus()
            self._app.processEvents()
            _press_key = QKeySequence('Ctrl+Z')
            self.assertEqual(win.undo_action.shortcut(), _press_key)
            win.undo_action.trigger()
            self.assertEqual(win.battle_map.get_pos(left), (0, 0))
            self.assertEqual(left.moved_ft, 0)
            self.assertTrue(win.redo_action.isEnabled())
            self.assertEqual(win.redo_action.toolTip(), 'Повторить: ход Орк 3')

            win.redo_action.trigger()
            self.assertEqual(win.battle_map.get_pos(left), (0, 2))
            win.undo_action.trigger()
            win.selected = left
            win.on_cell(0, 4)
            self.assertFalse(win.redo_action.isEnabled())
            self.assertEqual(win.battle_map.get_pos(left), (0, 4))
            win.do_undo()
            self.assertEqual(win.battle_map.get_pos(left), (0, 0))
        finally:
            win.close()

    def test_shortcuts_undo_and_redo_move(self):
        win, left, _right = self._window()
        try:
            win.show()
            win.map_view.setFocus()
            self._app.setActiveWindow(win)
            self._app.processEvents()
            win.selected = left
            win.on_cell(2, 0)
            from PyQt6.QtTest import QTest
            QTest.keyClick(win.map_view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self._app.processEvents()
            self.assertEqual(win.battle_map.get_pos(left), (0, 0), 'Ctrl+Z')
            QTest.keyClick(
                win.map_view, Qt.Key.Key_Z,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            self._app.processEvents()
            self.assertEqual(win.battle_map.get_pos(left), (2, 0), 'Ctrl+Shift+Z')
            QTest.keyClick(win.map_view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self._app.processEvents()
            QTest.keyClick(win.map_view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
            self._app.processEvents()
            self.assertEqual(win.battle_map.get_pos(left), (2, 0), 'Ctrl+Y')
        finally:
            win.close()

    def test_drag_token_is_one_undo_step(self):
        win, left, _right = self._window()
        try:
            win.select_tab(3)
            win.show()
            win.map_view.rebuild(win.battle_map, win.sides, None)
            self._app.processEvents()
            cell = win.map_view.opts['cell']
            origin = win.map_view.mapFromScene(QPointF(cell * 0.5, cell * 0.5))
            # Якорь клетки (2, 0): центр клетки округляется в полуклетку .5.
            target = win.map_view.mapFromScene(QPointF(cell * 2 + 2, 2))
            _press(win.map_view, QEvent.Type.MouseButtonPress, origin)
            _press(win.map_view, QEvent.Type.MouseMove, target)
            _press(win.map_view, QEvent.Type.MouseButtonRelease, target)
            self.assertEqual(win.battle_map.get_pos(left), (2, 0))
            self.assertEqual(win.undo_action.text(), 'Отменить: ход Орк 3')
            win.do_undo()
            self.assertEqual(win.battle_map.get_pos(left), (0, 0))
        finally:
            win.close()

    def test_round_undo_restores_log_lines_and_redo_matches(self):
        win, left, right = self._window()
        try:
            before_hp = (left.hp, right.hp)
            win.run_round()
            self.assertEqual(win.round_no, 1)
            self.assertGreater(win.log_panel.model.rowCount(), 0)
            self.assertTrue(win.map_view._attack_items or win.battle_events)
            rows = win.log_panel.model.rowCount()
            hp = (left.hp, right.hp)
            text = [event.text for event in win.battle_events]
            win.do_undo()
            self.assertEqual(win.round_no, 0)
            self.assertEqual((left.hp, right.hp), before_hp)
            self.assertEqual(win.log_panel.model.rowCount(), 0)
            self.assertEqual(win.map_view._attack_items, [])
            win.do_redo()
            self.assertEqual(win.round_no, 1)
            self.assertEqual((left.hp, right.hp), hp)
            self.assertEqual([event.text for event in win.battle_events], text)
            self.assertEqual(win.log_panel.model.rowCount(), rows)
        finally:
            win.close()

    def test_edit_alliance_and_side_cards(self):
        win, left, _right = self._window()
        try:
            sheet = win.open_creature_sheet([left])
            self.assertFalse(sheet.isModal())
            sheet.name.setText('Орк-вождь')
            sheet.ac.setValue(19)
            sheet.hp.setValue(left.max_hp)
            self.assertTrue(sheet.apply_changes())
            self.assertEqual(left.ac, 19)
            self.assertEqual(left.name, 'Орк-вождь')
            win.do_undo()
            self.assertEqual(left.ac, 14)
            self.assertEqual(left.name, 'Орк 3')
            win.do_redo()
            self.assertEqual(left.name, 'Орк-вождь')
            sheet.close()

            third = _fighter('Гном 1', 2, hp=10)
            win.sides.append([third])
            win.side_names.append('Гномы')
            win.battle_map.place(third, 4, 0)
            _baseline(win)
            win.refresh_alliances()
            win.all_vars[0][1].setChecked(True)
            win.apply_alliances()
            self.assertIn(1, left.ignore_sides)
            win.do_undo()
            self.assertEqual(left.ignore_sides, set())
            self.assertFalse(win.all_vars[0][1].isChecked())

            cards = len(win.cards)
            win.add_card()
            self.assertEqual(len(win.cards), cards + 1)
            win.do_undo()
            self.assertEqual(len(win.cards), cards)

            with mock.patch.object(QMessageBox, 'question',
                                   return_value=QMessageBox.StandardButton.Yes):
                win.remove_card(win.cards[-1])
            self.assertEqual(len(win.cards), cards - 1)
            win.do_undo()
            self.assertEqual(len(win.cards), cards)

            EnemyFactory.register_type(
                'Вампир тест', hp=50, ac=15,
                attacks=[{'name': 'Укус', 'attack_bonus': 6, 'damage_dice_count': 1,
                          'damage_dice_type': 'd6', 'damage_modifier': 3,
                          'damage_type': 'колющий'}])
            win._apply_composition(
                win.cards[0], {'army_type': 'Вампир тест', 'strategy': 'агрессивная'})
            self.assertEqual(win.cards[0]['type'], 'Вампир тест')
            win.do_undo()
            self.assertNotEqual(win.cards[0]['type'], 'Вампир тест')
            self.assertNotIn('Вампир тест', EnemyFactory.CUSTOM_TYPES)
        finally:
            win.close()

    def test_load_settings_clears_history(self):
        win, left, _right = self._window()
        try:
            win.selected = left
            win.on_cell(0, 2)
            self.assertTrue(win.undo_action.isEnabled())
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, 'other.json')
                with open(path, 'w', encoding='utf-8') as handle:
                    json.dump({'num_sides': 2, 'side_names': ['А', 'Б'],
                               'side_counts': [1, 1],
                               'army_types': ['орк', 'эльф'],
                               'strategy_types': ['случайная', 'случайная']}, handle)
                with mock.patch.object(QFileDialog, 'getOpenFileName',
                                       return_value=(path, '')):
                    win.load_settings()
            self.assertFalse(win.undo_action.isEnabled())
            self.assertFalse(win.redo_action.isEnabled())
            self.assertFalse(win.history.can_undo())
            self.assertEqual(win.cards[0]['name'].text(), 'А')
        finally:
            win.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
