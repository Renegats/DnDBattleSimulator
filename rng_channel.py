"""Локальный генератор одного боя.

Пакетный прогон идёт в фоновом потоке (и, по желанию, в других процессах).
Кости карты и случайной тактики читаются отсюда, а не из модульного random,
чтобы серия не сдвигала броски интерфейса и не зависела от чужого seed.
"""
import contextvars

_current = contextvars.ContextVar('battle_rng', default=None)


def active(fallback):
    """Генератор боя, если он включён, иначе fallback (обычно модуль random)."""
    found = _current.get()
    return fallback if found is None else found


class bound:
    """На время боя подменяет генератор в этом потоке."""

    def __init__(self, rng):
        self._rng = rng
        self._token = None

    def __enter__(self):
        self._token = _current.set(self._rng)
        return self._rng

    def __exit__(self, *_exc):
        _current.reset(self._token)
        return False
