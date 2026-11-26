"""Групповое выделение, групповые действия и один шаг отмены.

Запускать с QT_QPA_PLATFORM=offscreen.
"""
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QPointF, Qt, QEvent
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from battle_history import capture_battle
from battle_map_model import BattleMap
from entities import Attack, Enemy
from qt_app import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _fighter(name, side, hp=30, speed=30):
    enemy = Enemy(name, hp, 14, [Attack('Секира', 5, 1, 'd12', 3, 'рубящий')], side,
                  speed=speed)
    enemy.ability_scores = {'dex': 12}
    enemy.ability_mods = {'dex': 1}
    enemy.size = 'Средний'
    return enemy


def _baseline(win):
    win.history.clear()
    win._current = capture_battle(win)
    win._sync_history_actions()


class TestGroupSelect(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def _window(self):
        win = MainWindow()
        left = _fighter('Орк 1', 0)
        mid = _fighter('Орк 2', 0, hp=22)
        right = _fighter('Эльф 1', 1, hp=18)
        far = _fighter('Эльф 2', 1, hp=16)
        win.sides = [[left, mid], [right, far]]
        win.side_names = ['Орки', 'Эльфы']
        win.ignore_sides = {}
        win.battle_map = BattleMap(12, 8)
        win.battle_map.place(left, 1, 1)
        win.battle_map.place(mid, 2, 1)
        win.battle_map.place(right, 6, 1)
        win.battle_map.place(far, 8, 4)
        win.rebuild_battle_lists()
        win.map_view.rebuild(win.battle_map, win.sides, None)
        win.resize(1100, 720)
        _baseline(win)
        return win, left, mid, right, far

    def _press(self, view, pos, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(pos), button, button, mods)
        view.mousePressEvent(event)

    def _move(self, view, pos, mods=Qt.KeyboardModifier.NoModifier):
        event = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(pos), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, mods)
        view.mouseMoveEvent(event)

    def _release(self, view, pos, mods=Qt.KeyboardModifier.NoModifier):
        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(pos), Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton, mods)
        view.mouseReleaseEvent(event)

    def test_marquee_selects_tokens_inside_and_ignores_outside(self):
        win, left, mid, right, _far = self._window()
        try:
            win.show()
            self._app.processEvents()
            view = win.map_view
            cell = view.opts['cell']
            a = view.mapFromScene(QPointF(cell * 0.4, cell * 0.4))
            b = view.mapFromScene(QPointF(cell * 3.6, cell * 2.6))
            self._press(view, a)
            self._move(view, b)
            self._release(view, b)
            self._app.processEvents()
            self.assertCountEqual(win.selection, [left, mid])
            self.assertNotIn(right, win.selection)
            self.assertEqual(win._sel_label.text(), 'Выделено: 2')
            self.assertIn(left, win.selection)
            boxes = win.side_checks[0]
            self.assertTrue(boxes[0].isChecked())
            self.assertTrue(boxes[1].isChecked())
            self.assertFalse(win.side_checks[1][0].isChecked())
        finally:
            win.close()

    def test_ctrl_click_toggles_and_escape_clears_and_ctrl_a_selects_all(self):
        win, left, mid, right, far = self._window()
        try:
            win.set_selection([left])
            win.toggle_selection(mid)
            self.assertCountEqual(win.selection, [left, mid])
            win.toggle_selection(left)
            self.assertEqual(win.selection, [mid])
            win.select_all_tokens()
            self.assertEqual(len(win.selection), 4)
            self.assertEqual(win._sel_label.text(), 'Выделено: 4')
            win._on_escape()
            self.assertEqual(win.selection, [])
            self.assertIsNone(win.selected)
            win.select_side(1)
            self.assertCountEqual(win.selection, [right, far])
        finally:
            win.close()

    def test_select_all_shortcut_and_side_menu(self):
        win, _left, _mid, _right, _far = self._window()
        try:
            menu_action = next(action for action in win.menu_view.actions()
                               if action.text() == 'Выделение')
            select_menu = menu_action.menu()
            texts = [action.text() for action in select_menu.actions()]
            self.assertIn('Выделить всех', texts)
            self.assertIn('Снять выделение', texts)
            self.assertIn('Выделить сторону', texts)
            all_action = next(action for action in select_menu.actions()
                              if action.objectName() == 'select_all')
            all_action.trigger()
            self.assertEqual(len(win.selection), 4)
            win._fill_side_select_menu()
            side_actions = [action.text() for action in win._side_select_menu.actions()]
            self.assertTrue(any(text.startswith('Орки') for text in side_actions))
            win._side_select_menu.actions()[1].trigger()
            self.assertEqual({enemy.side for enemy in win.selection}, {1})
        finally:
            win.close()

    def test_roster_checkbox_syncs_both_ways(self):
        win, left, mid, _right, _far = self._window()
        try:
            win.side_checks[0][0].setChecked(True)
            win.side_checks[0][1].setChecked(True)
            self._app.processEvents()
            self.assertCountEqual(win.selection, [left, mid])
            win.set_selection([_far])
            self.assertFalse(win.side_checks[0][0].isChecked())
            self.assertTrue(win.side_checks[1][1].isChecked())
            win.side_all_checks[0].click()
            self._app.processEvents()
            self.assertIn(left, win.selection)
            self.assertIn(mid, win.selection)
        finally:
            win.close()

    def test_group_menu_items(self):
        win, left, mid, _right, _far = self._window()
        try:
            menu = win.build_group_menu([left, mid])
            texts = [action.text() for action in menu.actions()]
            for title in ('Карточка выделенных', 'Дублировать', 'Удалить…', 'Переместить',
                          'Нанести урон…', 'Лечить…'):
                self.assertIn(title, texts)
            self.assertEqual(menu.objectName(), 'group_menu')
            single = win.build_token_menu(left)
            self.assertIn('Карточка существа', [action.text() for action in single.actions()])
            self.assertNotIn('Карточка выделенных',
                             [action.text() for action in single.actions()])
        finally:
            win.close()

    def test_group_shift_preserves_shape_and_is_one_undo(self):
        win, left, mid, _right, _far = self._window()
        try:
            win.set_selection([left, mid], primary=left)
            _baseline(win)
            self.assertTrue(win.shift_group(left, 4, 3))
            self.assertEqual(win.battle_map.get_pos(left), (4, 3))
            self.assertEqual(win.battle_map.get_pos(mid), (5, 3))
            self.assertEqual(win.history.undo_label(), 'перемещение группы (2)')
            self.assertEqual(len(win.history), 1)
            win.do_undo()
            self.assertEqual(win.battle_map.get_pos(left), (1, 1))
            self.assertEqual(win.battle_map.get_pos(mid), (2, 1))
            win.do_redo()
            self.assertEqual(win.battle_map.get_pos(left), (4, 3))
            self.assertEqual(win.battle_map.get_pos(mid), (5, 3))
        finally:
            win.close()

    def test_group_shift_rejects_wall_without_partial_move(self):
        win, left, mid, _right, _far = self._window()
        try:
            win.battle_map.set_terrain(4, 1, 'wall')
            win.set_selection([left, mid], primary=left)
            _baseline(win)
            self.assertFalse(win.shift_group(left, 4, 1))
            self.assertEqual(win.battle_map.get_pos(left), (1, 1))
            self.assertEqual(win.battle_map.get_pos(mid), (2, 1))
            self.assertEqual(len(win.history), 0)
        finally:
            win.close()

    def test_group_delete_duplicate_side_damage_and_condition_are_single_steps(self):
        win, left, mid, right, _far = self._window()
        try:
            win.set_selection([left, mid])
            _baseline(win)
            with mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                self.assertTrue(win.delete_group([left, mid]))
            self.assertNotIn(left, win.sides[0])
            self.assertEqual(win.history.undo_label(), 'удаление группы (2)')
            self.assertEqual(len(win.history), 1)
            win.do_undo()
            restored = {enemy.name: enemy for side in win.sides for enemy in side}
            self.assertIn('Орк 1', restored)
            self.assertIn('Орк 2', restored)
            self.assertEqual(win.battle_map.get_pos(restored['Орк 1']), (1, 1))
            self.assertEqual(win.battle_map.get_pos(restored['Орк 2']), (2, 1))
            left = restored['Орк 1']
            mid = restored['Орк 2']

            _baseline(win)
            clones = win.duplicate_group([left, mid])
            self.assertEqual(len(clones), 2)
            self.assertEqual(win.history.undo_label(), 'дублирование группы (2)')
            self.assertEqual(len(win.history), 1)
            self.assertEqual(len(win.sides[0]), 4)
            win.do_undo()
            self.assertEqual(len(win.sides[0]), 2)

            _baseline(win)
            win.change_group_side([left, mid], 1)
            self.assertEqual(left.side, 1)
            self.assertIn(left, win.sides[1])
            self.assertEqual(win.history.undo_label(), 'сторона группы (2)')
            win.do_undo()
            self.assertEqual(left.side, 0)
            self.assertIn(left, win.sides[0])
            self.assertEqual(len(win.history), 0)

            _baseline(win)
            win._impose_group([left, right], 'frightened')
            self.assertTrue(any(item.get('id') == 'frightened' for item in left.conditions))
            self.assertTrue(any(item.get('id') == 'frightened' for item in right.conditions))
            self.assertEqual(len(win.history), 1)
            win.do_undo()
            self.assertFalse(left.conditions)

            _baseline(win)
            with mock.patch('qt_app.QInputDialog.getInt', return_value=(5, True)):
                win.damage_group([left, mid])
            self.assertEqual(left.hp, 25)
            self.assertEqual(mid.hp, 17)
            self.assertEqual(win.history.undo_label(), 'урон группе (2)')
            win.do_undo()
            self.assertEqual(left.hp, 30)
            self.assertEqual(mid.hp, 22)

            left.hp = 10
            _baseline(win)
            with mock.patch('qt_app.QInputDialog.getInt', return_value=(6, True)):
                win.heal_group([left, mid])
            self.assertEqual(left.hp, 16)
            self.assertEqual(mid.hp, 22)
            self.assertEqual(len(win.history), 1)
            win.do_undo()
            self.assertEqual(left.hp, 10)
        finally:
            win.close()

    def test_group_sheet_is_one_undo_step(self):
        win, left, mid, _right, _far = self._window()
        try:
            win.set_selection([left, mid])
            _baseline(win)
            sheet = win.open_creature_sheet(win.selection)
            sheet.ac.setValue(18)
            self.assertTrue(sheet.apply_changes())
            self.assertEqual(left.ac, 18)
            self.assertEqual(mid.ac, 18)
            self.assertEqual(win.history.undo_label(), 'правка: 2 существ')
            self.assertEqual(len(win.history), 1)
            win.do_undo()
            self.assertEqual(left.ac, 14)
            self.assertEqual(mid.ac, 14)
        finally:
            win.close()


if __name__ == '__main__':
    unittest.main()
