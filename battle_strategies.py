from abc import ABC, abstractmethod
import random


def distance_ft_between(a, b):
    """Дистанция между токенами в футах (0, если карты/позиций нет)"""
    pa, pb = getattr(a, 'pos', None), getattr(b, 'pos', None)
    if not pa or not pb:
        return 0
    return max(abs(pa[0] - pb[0]), abs(pa[1] - pb[1])) * 5


def reachable_attacks(attacker, target):
    """Атаки, достающие цель СЕЙЧАС. Если ни одна не достаёт - все атаки
    (юнит подойдёт в фазе движения, и атаку выберут заново)"""
    dist = distance_ft_between(attacker, target)
    ok = [a for a in attacker.attacks if getattr(a, 'range_ft', 5) >= dist]
    return ok if ok else list(attacker.attacks)


def damage_score(a):
    """Оценка среднего потенциала урона атаки"""
    return a.damage_dice_count * int(a.damage_dice_type[1:]) + a.damage_modifier


class BattleStrategy(ABC):
    """Абстрактный класс для стратегий поведения врагов в бою"""
    @abstractmethod
    def select_target(self, attacker, all_sides, ignore_sides):
        pass

    @abstractmethod
    def select_attack(self, attacker, target):
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
        return min(potential_targets, key=lambda e: e.hp)

    def select_attack(self, attacker, target):
        # Бьём тем, что ДОСТАЁТ: вблизи меч, издалека лук!
        return max(reachable_attacks(attacker, target), key=damage_score)


class DefensiveStrategy(BattleStrategy):
    """Защитная стратегия - атакует самого опасного врага"""
    def select_target(self, attacker, all_sides, ignore_sides):
        potential_targets = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx != attacker.side and side_idx not in ignore_sides and side_idx not in attacker.ignore_sides:
                potential_targets.extend([e for e in side_enemies if e.alive])
        if not potential_targets:
            return None
        return max(potential_targets, key=lambda e: max((a.attack_bonus for a in e.attacks), default=0))

    def select_attack(self, attacker, target):
        if not attacker.attacks:
            return None
        return max(reachable_attacks(attacker, target), key=lambda a: a.attack_bonus)


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
        return random.choice(reachable_attacks(attacker, target))


class SupportStrategy(BattleStrategy):
    """Тактика поддержки - сначала лечит союзников, затем атакует"""
    def select_target(self, attacker, all_sides, ignore_sides):
        healing_targets = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx == attacker.side and side_idx not in ignore_sides:
                healing_targets.extend([e for e in side_enemies if e.alive and e.hp < e.max_hp * 0.7])
        if healing_targets:
            return min(healing_targets, key=lambda e: e.hp / e.max_hp)
        potential_targets = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx != attacker.side and side_idx not in ignore_sides and side_idx not in attacker.ignore_sides:
                potential_targets.extend([e for e in side_enemies if e.alive])
        if not potential_targets:
            return None
        return min(potential_targets, key=lambda e: e.hp)

    def select_attack(self, attacker, target):
        if not attacker.attacks:
            return None
        if target.side == attacker.side:
            healing_attacks = [a for a in attacker.attacks if
                               "лечение" in a.name.lower() or "heal" in a.name.lower()
                               or "восстановление" in a.name.lower()]
            if healing_attacks:
                return healing_attacks[0]
        return max(reachable_attacks(attacker, target), key=damage_score)