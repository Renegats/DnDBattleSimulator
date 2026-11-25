"""Точка входа: приложение на Qt.

faulthandler включён: при жёстком вылете на уровне C++ (access violation,
fail-fast) в консоль печатается Python-стек — код выхода больше не будет
единственной уликой.
"""
import faulthandler
import sys
import traceback

faulthandler.enable()


def _excepthook(kind, value, tb):
    traceback.print_exception(kind, value, tb)


sys.excepthook = _excepthook


def main():
    from PyQt6.QtWidgets import QApplication
    from qt_async import install
    from qt_app import MainWindow
    app = QApplication(sys.argv)
    install(app)
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
