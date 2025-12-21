from abc import ABC, abstractmethod


class Observer(ABC):
    """Абстрактный класс наблюдателя"""

    @abstractmethod
    def update(self, subject):
        """Метод для обновления состояния наблюдателя"""
        pass


class Subject:
    """Субъект, за которым наблюдают"""

    def __init__(self):
        self._observers = []

    def attach(self, observer):
        """Добавляет наблюдателя"""
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer):
        """Удаляет наблюдателя"""
        try:
            self._observers.remove(observer)
        except ValueError:
            pass

    def notify(self):
        """Оповещает всех наблюдателей об изменении"""
        for observer in self._observers:
            observer.update(self)