"""Меню, тулбар и боковая панель. QT_QPA_PLATFORM=offscreen."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QDockWidget, QToolBar, QToolButton

from qt_app import SETTINGS_APP, SETTINGS_ORG, MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _settings():
    return QSettings(SETTINGS_ORG, SETTINGS_APP + '.test')


def _texts(menu):
    return [action.text() for action in menu.actions()]


class TestQtShell(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def setUp(self):
        _settings().clear()
        self.win = MainWindow()

    def tearDown(self):
        self.win.close()
        _settings().clear()

    def _menu(self, title):
        return next(action.menu() for action in self.win.menuBar().actions()
                    if action.text() == title)

    def test_menus_list_the_actions(self):
        self.assertEqual(
            [action.text() for action in self.win.menuBar().actions()],
            ['Файл', 'Правка', 'Бой', 'Симуляция', 'Вид'])
        edit = self._menu('Правка')
        self.assertEqual([action.objectName() for action in edit.actions()],
                         ['undo', 'redo'])
        self.assertEqual(self._menu('Симуляция').actions()[0].text(),
                         'Пакетная симуляция…')
        battle = _texts(self._menu('Бой'))
        for title in ('Провести раунд', 'Автобой', 'Пауза', 'Создать армии',
                      'Ручное управление', 'Настройки боя…'):
            self.assertIn(title, battle)
        file_menu = _texts(self._menu('Файл'))
        for title in ('Сохранить настройки', 'Загрузить настройки',
                      'Экспорт журнала', 'Экспорт карты PNG'):
            self.assertIn(title, file_menu)
        view = _texts(self._menu('Вид'))
        for title in ('Настройка армий', 'Карта боя', 'Панель боя',
                      'Участники', 'Журнал', 'Бестиарий'):
            self.assertIn(title, view)

    def test_toolbar_buttons_have_names_and_tips(self):
        bar = self.win.findChild(QToolBar, 'battle_toolbar')
        self.assertIsNotNone(bar)
        self.assertIsInstance(self.win.side_dock, QDockWidget)
        self.assertEqual(self.win.side_dock.objectName(), 'side_dock')
        self.assertEqual(self.win.side_tabs.count(), 3)
        self.assertEqual(
            [self.win.side_tabs.tabText(i) for i in range(3)],
            ['Участники', 'Журнал', 'Бестиарий'])
        buttons = {
            'armies_button': self.win.armies_btn,
            'create_button': self.win.create_btn,
            'round_button': self.win.round_btn,
            'auto_button': self.win.auto_btn,
            'pause_button': self.win.pause_btn,
            'undo_button': self.win.btn_undo,
            'redo_button': self.win.btn_redo,
            'settings_button': self.win.settings_btn,
        }
        for name, button in buttons.items():
            self.assertIsInstance(button, QToolButton)
            self.assertEqual(button.objectName(), name)
            self.assertTrue(button.toolTip(), name)
            self.assertFalse(button.icon().isNull(), name)
        self.assertTrue(self.win.auto_btn.isEnabled())
        self.assertFalse(self.win.pause_btn.isEnabled())
        self.assertEqual(self.win.batch_btn.text(), 'Пакетная симуляция…')
        self.assertEqual(self.win.crit_mode.currentData(), 'double_all')
        self.assertFalse(self.win.hide_hp.isChecked())
        self.assertTrue(self.win.auto_move.isChecked())

    def test_pages_and_saved_dock(self):
        self.assertEqual(self.win.stack.currentIndex(), 0)
        self.win.select_tab(3)
        self.assertEqual(self.win.stack.currentIndex(), 1)
        self.assertTrue(self.win.act_map_page.isChecked())
        self.win.show()
        self._app.processEvents()
        self.win.side_dock.hide()
        self.win._save_layout()
        self.win.close()
        again = MainWindow()
        try:
            again.show()
            self._app.processEvents()
            self.assertFalse(again.side_dock.isVisible())
            self.assertEqual(again.stack.currentIndex(), 1)
            again.reset_layout()
            self._app.processEvents()
            self.assertTrue(again.side_dock.isVisible())
        finally:
            again.close()
