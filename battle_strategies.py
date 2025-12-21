from abc import ABC, abstractmethod
import random


class BattleStrategy(ABC):
    """Абстрактный класс для стратегий поведения врагов в бою"""

    @abstractmethod
    def select_target(self, attacker, all_sides, ignore_sides):
        """Выбирает цель для атаки"""
        pass

    @abstractmethod
    def select_attack(self, attacker, target):
        """Выбирает атаку для использования"""
        pass


class AggressiveStrategy(BattleStrategy):
    """Агрессивная стратегия - атакует самого слабого врага"""

    def select_target(self, attacker, all_sides, ignore_sides):
        potential_targets = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx != attacker.side and side_idx not in ignore_sides and side_idx not in attacker.ignore_sides:
                potential_targets.extend([e for e in side_enemies if e.alive])

        if not potential_targets:
            return None

        # Выбираем самого слабого противника
        return min(potential_targets, key=lambda e: e.hp)

    def select_attack(self, attacker, target):

        # Если есть атаки, выбираем ту, что наносит больше урона
        return max(attacker.attacks,
                   key=lambda a: a.damage_dice_count * int(a.damage_dice_type[1:]) + a.damage_modifier)


class DefensiveStrategy(BattleStrategy):
    """Защитная стратегия - атакует самого опасного врага"""

    def select_target(self, attacker, all_sides, ignore_sides):
        potential_targets = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx != attacker.side and side_idx not in ignore_sides and side_idx not in attacker.ignore_sides:
                potential_targets.extend([e for e in side_enemies if e.alive])

        if not potential_targets:
            return None

        # Выбираем самого опасного противника (с максимальной атакой)
        return max(potential_targets, key=lambda e: max((a.attack_bonus for a in e.attacks), default=0))

        """Выбирает атаку с максимальным уроном"""
        if not attacker.attacks:
            return None
    def select_attack(self, attacker, target):
        """Выбирает атаку с максимальным бонусом к попаданию"""
        if not attacker.attacks:
            return None

        return max(attacker.attacks, key=lambda a: a.attack_bonus)


class RandomStrategy(BattleStrategy):
    """Случайная стратегия - выбирает случайную цель и атаку"""

    def select_target(self, attacker, all_sides, ignore_sides):
        potential_targets = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx != attacker.side and side_idx not in ignore_sides and side_idx not in attacker.ignore_sides:
                potential_targets.extend([e for e in side_enemies if e.alive])

        if not potential_targets:
            return None

        return random.choice(potential_targets)

    def select_attack(self, attacker, target):
        if not attacker.attacks:
            return None

        # Случайная атака из доступных
        return random.choice(attacker.attacks)


class SupportStrategy(BattleStrategy):
    """Тактика поддержки - сначала лечит союзников, затем атакует"""

    def select_target(self, attacker, all_sides, ignore_sides):
        # Сначала ищем раненых союзников для помощи
        healing_targets = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx == attacker.side and side_idx not in ignore_sides:
                healing_targets.extend([e for e in side_enemies if e.alive and e.hp < e.max_hp * 0.7])

        if healing_targets:
            # Выбираем самого раненого союзника
            return min(healing_targets, key=lambda e: e.hp / e.max_hp)

        # Если некому помогать, атакуем врагов
        potential_targets = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx != attacker.side and side_idx not in ignore_sides and side_idx not in attacker.ignore_sides:
                potential_targets.extend([e for e in side_enemies if e.alive])

        if not potential_targets:
            return None

        # Выбираем самого слабого противника
        return min(potential_targets, key=lambda e: e.hp)

    def select_attack(self, attacker, target):
        """Выбирает атаку в зависимости от цели"""
        if not attacker.attacks:
            return None

        # Если цель - союзник, ищем атаку с лечением
        if target.side == attacker.side:
            healing_attacks = [a for a in attacker.attacks if
                               "лечение" in a.name.lower() or "heal" in a.name.lower() or "восстановление" in a.name.lower()]
            if healing_attacks:
                return healing_attacks[0]

        # Для врагов используем агрессивную стратегию
        return max(attacker.attacks,
                   key=lambda a: a.damage_dice_count * int(a.damage_dice_type[1:]) + a.damage_modifier)