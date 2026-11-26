"""Карточка существа, контекстное меню карты и отмена этих правок.

Запускать с QT_QPA_PLATFORM=offscreen.
"""
import json
import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QPointF, Qt, QEvent
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from battle_history import capture_battle
from battle_map_model import BattleMap
from entities import Attack, Enemy
from factory import EnemyFactory
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


def _texts(menu):
    return [action.text() for action in menu.actions()]


class TestCreatureSheet(unittest.TestCase):

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
        win.rebuild_battle_lists()
        win.map_view.rebuild(win.battle_map, win.sides, None)
        _baseline(win)
        return win, left, right

    def test_no_army_page_and_crit_stays_double_all(self):
        win, _left, _right = self._window()
        try:
            self.assertEqual(win.stack.count(), 1)
            self.assertIs(win.stack.currentWidget(), win.map_page)
            self.assertFalse(win.sides_dialog.isVisible())
            self.assertEqual(win.crit_mode.currentData(), 'double_all')
            win.show_sides()
            self._app.processEvents()
            self.assertTrue(win.sides_dialog.isVisible())
            self.assertTrue(win.armies_btn.isChecked())
            win.sides_dialog.close()
            self._app.processEvents()
            self.assertFalse(win.armies_btn.isChecked())
        finally:
            win.close()

    def test_token_and_cell_menus(self):
        win, left, _right = self._window()
        try:
            menu = win.build_token_menu(left)
            texts = _texts(menu)
            for title in ('Карточка существа', 'Дублировать', 'Удалить…', 'Переместить'):
                self.assertIn(title, texts)
            self.assertIn('Сменить сторону', texts)
            self.assertIn('Наложить состояние', texts)
            side = next(action.menu() for action in menu.actions()
                        if action.text() == 'Сменить сторону')
            side_texts = _texts(side)
            self.assertIn('Орки', side_texts)
            self.assertIn('Эльфы', side_texts)
            self.assertIn('Новая сторона…', side_texts)
            checked = [action.text() for action in side.actions() if action.isChecked()]
            self.assertEqual(checked, ['Орки'])

            cell = win.build_cell_menu(4, 2)
            self.assertEqual(_texts(cell), ['Добавить существо сюда…'])
            self.assertEqual(cell.actions()[0].objectName(), 'cell_add')
        finally:
            win.close()

    def test_right_click_routes_token_and_empty_cell(self):
        win, left, _right = self._window()
        try:
            win.show()
            self._app.processEvents()
            cell = win.map_view.opts['cell']
            opened = []

            def token_menu(enemy, _pos):
                opened.append(('token', enemy))

            def cell_menu(x, y, _pos):
                opened.append(('cell', x, y))

            win.map_view.token_menu.disconnect()
            win.map_view.cell_menu.disconnect()
            win.map_view.token_menu.connect(token_menu)
            win.map_view.cell_menu.connect(cell_menu)

            def press(pos, button):
                event = QMouseEvent(
                    QEvent.Type.MouseButtonPress, QPointF(pos), button, button,
                    Qt.KeyboardModifier.NoModifier)
                win.map_view.mousePressEvent(event)

            origin = win.map_view.mapFromScene(QPointF(cell * 0.5, cell * 0.5))
            press(origin, Qt.MouseButton.RightButton)
            self.assertEqual(opened[0][0], 'token')
            self.assertIs(opened[0][1], left)

            empty = win.map_view.mapFromScene(QPointF(cell * 5 + 2, cell * 3 + 2))
            press(empty, Qt.MouseButton.RightButton)
            self.assertEqual(opened[1][0], 'cell')
            self.assertEqual(opened[1][1:], (5.0, 3.0))
        finally:
            win.close()

    def test_sheet_edits_stats_side_and_undo(self):
        win, left, _right = self._window()
        try:
            sheet = win.open_creature_sheet([left])
            self.assertEqual(sheet.objectName(), 'creature_sheet')
            self.assertFalse(sheet.isModal())
            self.assertTrue(sheet._sec_attacks.arrow.isChecked())
            self.assertTrue(sheet._sec_conditions.arrow.isChecked())
            sheet.name.setText('Вождь')
            sheet.hp.setValue(12)
            sheet.max_hp.setValue(40)
            sheet.ac.setValue(18)
            sheet.initiative.setValue(3)
            sheet.chars.texts['resistances'].setPlainText('огонь, холод')
            sheet.side.setCurrentText('Эльфы')
            self.assertTrue(sheet.apply_changes())
            self.assertEqual(left.name, 'Вождь')
            self.assertEqual(left.hp, 12)
            self.assertEqual(left.max_hp, 40)
            self.assertEqual(left.ac, 18)
            self.assertEqual(left.initiative_bonus, 3)
            self.assertEqual(left.resistances, ['огонь', 'холод'])
            self.assertEqual(left.side, 1)
            self.assertIn(left, win.sides[1])
            self.assertNotIn(left, win.sides[0])
            self.assertEqual(win.undo_action.text(), 'Отменить: правка: Орк 3')

            win.do_undo()
            self.assertEqual(left.name, 'Орк 3')
            self.assertEqual(left.hp, 30)
            self.assertEqual(left.max_hp, 30)
            self.assertEqual(left.ac, 14)
            self.assertEqual(left.initiative_bonus, 0)
            self.assertEqual(left.resistances, [])
            self.assertEqual(left.side, 0)
            self.assertIn(left, win.sides[0])
            self.assertNotIn(left, win.sides[1])

            win.do_redo()
            self.assertEqual(left.name, 'Вождь')
            self.assertEqual(left.side, 1)
            self.assertEqual(left.resistances, ['огонь', 'холод'])
            sheet.close()
        finally:
            win.close()

    def test_duplicate_delete_move_and_add_are_undoable(self):
        win, left, right = self._window()
        try:
            clone = win.duplicate_enemy(left)
            self.assertIsNotNone(clone)
            self.assertNotEqual(getattr(clone, 'uid', None), getattr(left, 'uid', None))
            self.assertEqual(clone.side, 0)
            self.assertIn(clone, win.sides[0])
            placed = win.battle_map.get_pos(clone)
            self.assertIsNotNone(placed)
            self.assertNotEqual(placed, (0, 0))
            self.assertNotEqual(placed, (1, 0))
            win.do_undo()
            self.assertNotIn(clone, win.sides[0])
            self.assertIsNone(win.battle_map.get_pos(clone))
            win.do_redo()
            names = [enemy.name for enemy in win.sides[0]]
            self.assertIn(clone.name, names)

            win.change_enemy_side(left, -1)
            self.assertEqual(left.side, 2)
            self.assertEqual(win.side_names[2], 'Сторона C')
            self.assertIn(left, win.sides[2])
            win.do_undo()
            self.assertEqual(left.side, 0)
            self.assertIn(left, win.sides[0])

            win.begin_relocate(right)
            win.on_cell(6, 4)
            self.assertEqual(win.battle_map.get_pos(right), (6, 4))
            self.assertEqual(right.moved_ft, 0)
            self.assertIsNone(win._relocate)
            win.do_undo()
            self.assertEqual(win.battle_map.get_pos(right), (1, 0))

            placed = win.add_creature_at(4, 2, 'орк', side=1, name='Дозорный')
            self.assertEqual(placed.name, 'Дозорный')
            self.assertEqual(placed.side, 1)
            self.assertEqual(win.battle_map.get_pos(placed), (4, 2))
            self.assertEqual(win.crit_mode.currentData(), 'double_all')
            win.do_undo()
            self.assertFalse(any(enemy.name == 'Дозорный'
                                 for side in win.sides for enemy in side))

            with mock.patch.object(QMessageBox, 'question',
                                   return_value=QMessageBox.StandardButton.Yes):
                self.assertTrue(win.delete_enemy(left))
            self.assertFalse(any(enemy.name == 'Орк 3' for enemy in win.sides[0]))
            win.do_undo()
            restored = next(enemy for enemy in win.sides[0] if enemy.name == 'Орк 3')
            self.assertEqual(win.battle_map.get_pos(restored), (0, 0))

            with mock.patch.object(QMessageBox, 'question',
                                   return_value=QMessageBox.StandardButton.No):
                self.assertFalse(win.delete_enemy(restored))
            self.assertIn(restored, win.sides[0])
        finally:
            win.close()

    def test_clear_field_keeps_side_templates(self):
        win, left, _right = self._window()
        try:
            cards = len(win.cards)
            with mock.patch.object(QMessageBox, 'question',
                                   return_value=QMessageBox.StandardButton.Yes):
                win.clear_field()
            self.assertFalse(any(win.sides))
            self.assertEqual(len(win.cards), cards)
            self.assertIsNone(win.battle_map.get_pos(left))
            win.do_undo()
            restored = next(enemy for enemy in win.sides[0] if enemy.name == 'Орк 3')
            self.assertEqual(win.battle_map.get_pos(restored), (0, 0))
        finally:
            win.close()

    def test_add_dialog_reports_side_and_type(self):
        win, _left, _right = self._window()
        try:
            from qt_creature_sheet import AddCreatureDialog
            dialog = AddCreatureDialog(
                win, ['орк', 'эльф'], ['Орки', 'Эльфы'], cell=(3, 1), current_type='орк')
            self.assertEqual(dialog.windowTitle(), 'Добавить существо сюда')
            dialog.name.setText('Лазутчик')
            dialog.side.setCurrentText('Эльфы')
            dialog.tactic.setCurrentText('агрессивная')
            data = dialog.result_data()
            self.assertEqual(data['name'], 'Лазутчик')
            self.assertEqual(data['type'], 'орк')
            self.assertEqual(data['side'], 1)
            self.assertEqual(data['strategy'], 'агрессивная')
            dialog.side.setCurrentIndex(dialog.side.count() - 1)
            self.assertEqual(dialog.result_data()['side'], -1)
            dialog.reject()
        finally:
            win.close()

    def test_menu_delete_asks_before_removing(self):
        win, left, _right = self._window()
        try:
            menu = win.build_token_menu(left)
            action = next(item for item in menu.actions() if item.text() == 'Удалить…')
            with mock.patch.object(QMessageBox, 'question',
                                   return_value=QMessageBox.StandardButton.Yes) as ask:
                action.trigger()
            ask.assert_called_once()
            self.assertFalse(any(enemy.name == 'Орк 3' for enemy in win.sides[0]))
            win.do_undo()
            self.assertTrue(any(enemy.name == 'Орк 3' for enemy in win.sides[0]))
        finally:
            win.close()

    def test_prompt_from_button_does_not_treat_click_as_coordinate(self):
        win, _left, _right = self._window()
        try:
            seen = {}

            def fake_exec(dialog):
                seen['title'] = dialog.windowTitle()
                dialog.name.setText('Гость')
                dialog.kind.setCurrentText('орк')
                return QDialog.DialogCode.Accepted

            with mock.patch.object(QDialog, 'exec', fake_exec):
                enemy = win.prompt_add_creature(False)
            self.assertEqual(seen['title'], 'Добавить существо')
            self.assertIsNotNone(enemy)
            self.assertEqual(enemy.name, 'Гость')
            self.assertIsNotNone(win.battle_map.get_pos(enemy))
        finally:
            win.close()
