"""Точка входа: Qt по умолчанию, Tkinter — страховочный путь.

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
    try:
        from PyQt6.QtWidgets import QApplication
        from qt_async import install
        from qt_app import MainWindow
    except ImportError as exc:
        print(f'[main] Qt недоступен ({exc}) — запускаю Tkinter-версию.', file=sys.stderr)
        from main_tk import main as tk_main
        tk_main()
        return
    app = QApplication(sys.argv)
    install(app)
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()