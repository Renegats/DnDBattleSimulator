import random
from typing import List, Tuple
from observer import Subject
from battle_strategies import BattleStrategy, RandomStrategy


class Attack:
    """Класс для представления атаки существа"""

    def __init__(self, name: str, attack_bonus: int, damage_dice_count: int,
                 damage_dice_type: str, damage_modifier: int, damage_type: str = ""):
        self.name = name
        self.attack_bonus = attack_bonus
        self.damage_dice_count = damage_dice_count
        self.damage_dice_type = damage_dice_type
        self.damage_modifier = damage_modifier
        self.damage_type = damage_type

    def to_dict(self):
        """Преобразует объект атаки в словарь для сохранения"""
        return {
            'name': self.name,
            'attack_bonus': self.attack_bonus,
            'damage_dice_count': self.damage_dice_count,
            'damage_dice_type': self.damage_dice_type,
            'damage_modifier': self.damage_modifier,
            'damage_type': self.damage_type
        }

    @classmethod
    def from_dict(cls, data):
        """Создает объект атаки из словаря"""
        return cls(
            data['name'],
            data['attack_bonus'],
            data['damage_dice_count'],
            data['damage_dice_type'],
            data['damage_modifier'],
            data.get('damage_type', '')
        )


class Enemy(Subject):
    """Класс для представления врага/существа в битве"""

    def __init__(self, name: str, hp: int, ac: int, attacks: List[Attack], side: int, regen=0):
        super().__init__()  # Инициализация Subject для паттерна "Наблюдатель"
        self.name = name
        self.max_hp = hp
        self.hp = hp
        self.ac = ac
        self.attacks = attacks
        self.side = side  # Номер стороны (0, 1, 2...)
        self.alive = True
        self.ignore_sides = set()  # Множество сторон, которые этот враг игнорирует
        self.strategy: BattleStrategy = RandomStrategy()  # Паттерн "Стратегия"
        self.regen = regen  # Регенерация здоровья (для троллей и подобных существ)

    def take_damage(self, damage: int):
        """Нанесение урона врагу"""
        actual_damage = max(0, damage)  # Урон не может быть отрицательным
        previous_hp = self.hp
        self.hp -= actual_damage
        if self.hp <= 0:
            self.alive = False
            self.hp = 0
            self.notify()  # Оповещаем наблюдателей об изменении состояния
            return False
        elif self.hp != previous_hp:
            self.notify()  # Оповещаем наблюдателей об изменении состояния

        return self.alive

    def perform_attack(self, attack: Attack, target_ac: int) -> Tuple[bool, int, int, bool, str]:
        """Выполнение атаки на цель"""
        attack_roll = random.randint(1, 20)
        total_attack = attack_roll + attack.attack_bonus
        critical = (attack_roll == 20)  # Критическое попадание при 20
        hit = total_attack >= target_ac or critical
        damage_info = ""
        if hit:
            # Расчет урона
            dice_type = int(attack.damage_dice_type.split('d')[1])
            damage = sum(random.randint(1, dice_type) for _ in range(attack.damage_dice_count)) + attack.damage_modifier
            # Удвоение урона при критическом попадании
            if critical:
                damage *= 2
            damage = max(0, damage)  # Урон не может быть отрицательным
            damage_info = f"{damage} урона"
            if attack.damage_type:
                damage_info += f" ({attack.damage_type})"
            return True, damage, total_attack, critical, damage_info
        return False, 0, total_attack, critical, damage_info

    def regenerate(self):
        """Регенерация здоровья в конце раунда"""
        if self.alive and self.regen > 0:
            prev_hp = self.hp
            self.hp = min(self.max_hp, self.hp + self.regen)
            if self.hp != prev_hp:
                self.notify()  # Оповещаем об изменении здоровья

    def to_dict(self):
        """Преобразует объект врага в словарь для сохранения"""
        return {
            'name': self.name,
            'max_hp': self.max_hp,
            'hp': self.hp,
            'ac': self.ac,
            'attacks': [attack.to_dict() for attack in self.attacks],
            'side': self.side,
            'alive': self.alive,
            'ignore_sides': list(self.ignore_sides),
            'strategy_type': self.strategy.__class__.__name__,
            'regen': self.regen
        }

    @classmethod
    def from_dict(cls, data):
        """Создает объект врага из словаря"""
        enemy = cls(
            data['name'],
            data['max_hp'],
            data['ac'],
            [Attack.from_dict(attack_data) for attack_data in data['attacks']],
            data['side'],
            data.get('regen', 0)
        )
        enemy.hp = data['hp']
        enemy.alive = data['alive']
        enemy.ignore_sides = set(data['ignore_sides'])

        # Восстановление стратегии из сохранения
        strategy_type = data.get('strategy_type', 'RandomStrategy')
        from battle_strategies import AggressiveStrategy, DefensiveStrategy, RandomStrategy, SupportStrategy
        if strategy_type == 'AggressiveStrategy':
            enemy.strategy = AggressiveStrategy()
        elif strategy_type == 'DefensiveStrategy':
            enemy.strategy = DefensiveStrategy()
        elif strategy_type == 'SupportStrategy':
            enemy.strategy = SupportStrategy()
        else:
            enemy.strategy = RandomStrategy()

        return enemy