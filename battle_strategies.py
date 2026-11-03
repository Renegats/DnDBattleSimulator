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
    """Абстрактная стратегия. Общие хелперы сбора целей и учёта дистанции."""

    @abstractmethod
    def select_target(self, attacker, all_sides, ignore_sides):
        pass

    @abstractmethod
    def select_attack(self, attacker, target):
        pass

    # ---------- общие хелперы ----------
    def _collect_enemies(self, attacker, all_sides, ignore_sides):
        """Живые враги attacker'a с учётом игнорируемых сторон."""
        enemies = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx == attacker.side:
                continue
            if side_idx in ignore_sides or side_idx in attacker.ignore_sides:
                continue
            enemies.extend([e for e in side_enemies if e.alive])
        return enemies

    def _pick_target(self, attacker, candidates, prefer_key):
        """Умный выбор цели в THREE приоритетах:
        1) враг в радиусе оружия -> бей прямо сейчас, не двигаясь;
        2) враг в радиусе (оружие + скорость) -> подойди и ударь;
        3) никого вокруг -> беги к ближайшему (а не к 'идеальному' через всю карту).
        Без карты distance=0 для всех -> приоритет 1 = все -> как раньше."""
        if not candidates:
            return None
        ma = getattr(attacker, 'multiattack', None)
        if ma:
            by_name = {a.name: getattr(a, 'range_ft', 5) for a in attacker.attacks}
            ranges = [by_name[s['attack']] for s in ma if s.get('attack') in by_name]
            max_range = min(ranges) if ranges else max(
                (getattr(a, 'range_ft', 5) for a in attacker.attacks), default=5)
        else:
            max_range = max((getattr(a, 'range_ft', 5) for a in attacker.attacks), default=5)
        speed = getattr(attacker, 'speed', 30)
        d = lambda e: distance_ft_between(attacker, e)
        tier1 = [e for e in candidates if d(e) <= max_range]  # ударь на месте
        if tier1:
            return prefer_key(tier1)
        tier2 = [e for e in candidates if d(e) <= max_range + speed]  # подойди и ударь
        if tier2:
            return prefer_key(tier2)
        return min(candidates, key=d)  # беги к ближайшему

class AggressiveStrategy(BattleStrategy):
    """Агрессивная - бьёт самого слабого ИЗ ДОСТУПНЫХ, иначе бежит к ближайшему."""
    def select_target(self, attacker, all_sides, ignore_sides):
        enemies = self._collect_enemies(attacker, all_sides, ignore_sides)
        return self._pick_target(attacker, enemies,
                                 lambda pool: min(pool, key=lambda e: e.hp))

    def select_attack(self, attacker, target):
        return max(reachable_attacks(attacker, target), key=damage_score)


class DefensiveStrategy(BattleStrategy):
    """Защитная - нейтрализует самого опасного ИЗ ДОСТУПНЫХ."""
    def select_target(self, attacker, all_sides, ignore_sides):
        enemies = self._collect_enemies(attacker, all_sides, ignore_sides)
        return self._pick_target(attacker, enemies,
                                 lambda pool: max(pool, key=lambda e:
                                                  max((a.attack_bonus for a in e.attacks), default=0)))

    def select_attack(self, attacker, target):
        if not attacker.attacks:
            return None
        return max(reachable_attacks(attacker, target), key=lambda a: a.attack_bonus)


class RandomStrategy(BattleStrategy):
    """Случайная - случайная цель из доступных (или ближайшая, если вокруг пусто)."""
    def select_target(self, attacker, all_sides, ignore_sides):
        enemies = self._collect_enemies(attacker, all_sides, ignore_sides)
        return self._pick_target(attacker, enemies, lambda pool: random.choice(pool))

    def select_attack(self, attacker, target):
        if not attacker.attacks:
            return None
        return random.choice(reachable_attacks(attacker, target))


class SupportStrategy(BattleStrategy):
    """Поддержка - лечит самого раненого СОЮЗНИКА из доступных, иначе бьёт врага."""
    def select_target(self, attacker, all_sides, ignore_sides):
        # Сначала раненые союзники (тоже с учётом дистанции - лекарь подбегает к ближнему)
        allies = []
        for side_idx, side_enemies in enumerate(all_sides):
            if side_idx == attacker.side and side_idx not in ignore_sides:
                allies.extend([e for e in side_enemies
                               if e.alive and e.hp < e.max_hp * 0.7])
        if allies:
            return self._pick_target(attacker, allies,
                                     lambda pool: min(pool, key=lambda e: e.hp / e.max_hp))
        # Союзников лечить некого - атакуем врага по правилам агрессора
        enemies = self._collect_enemies(attacker, all_sides, ignore_sides)
        return self._pick_target(attacker, enemies,
                                 lambda pool: min(pool, key=lambda e: e.hp))

    def select_attack(self, attacker, target):
        if not attacker.attacks:
            return None
        if target.side == attacker.side:
            healing = [a for a in attacker.attacks if
                       "лечение" in a.name.lower() or "heal" in a.name.lower()
                       or "восстановление" in a.name.lower()]
            if healing:
                return healing[0]
        return max(reachable_attacks(attacker, target), key=damage_score)