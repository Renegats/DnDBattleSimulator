"""Фоновые задачи без QThread: поток Python + очередь + QTimer в GUI-потоке.

Причина отказа от QThread: объект QThread, у которого последняя Python-ссылка
уходит в момент завершения потока, уничтожается сборщиком Python, пока поток
ещё выполняется -> Qt делает fail-fast (0xC0000602). Здесь ни один Qt-объект
не участвует в фоновой работе: поток пишет в queue.Queue, QTimer читает в
главном потоке и там же зовёт колбэки. Все QPixmap/QWidget остаются в GUI.
"""
import queue
import threading
import traceback

from PyQt6.QtCore import QTimer

_RESULTS = queue.Queue()
_PUMP = None
MAX_PER_TICK = 32


class Guard:
    """Флаг живости окна: результат закрытого диалога просто игнорируется."""

    def __init__(self):
        self.alive = True

    def drop(self):
        self.alive = False


def submit(fn, args=(), on_ok=None, on_fail=None, guard=None):
    """Запускает fn(*args) в фоновом потоке; колбэк придёт в GUI-потоке."""
    def runner():
        try:
            result = fn(*args)
        except Exception as exc:
            traceback.print_exc()
            _RESULTS.put((on_fail, guard, str(exc)))
            return
        _RESULTS.put((on_ok, guard, result))

    threading.Thread(target=runner, daemon=True, name='bg-task').start()


def _drain():
    for _ in range(MAX_PER_TICK):
        try:
            cb, guard, payload = _RESULTS.get_nowait()
        except queue.Empty:
            return
        if cb is None:
            continue
        if guard is not None and not guard.alive:
            continue
        try:
            cb(payload)
        except Exception:
            traceback.print_exc()


def install(app):
    """Ставит насос очереди на GUI-поток. Вызывать после QApplication."""
    global _PUMP
    if _PUMP is None:
        _PUMP = QTimer(app)
        _PUMP.setInterval(25)
        _PUMP.timeout.connect(_drain)
        _PUMP.start()
    return _PUMP