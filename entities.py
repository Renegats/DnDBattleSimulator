import random
from typing import List, Tuple

from observer import Subject
from battle_strategies import BattleStrategy, RandomStrategy


class Attack:
    """Атака существа. magical=True — оружие считается магическим и пробивает
    иммунитеты вида «дробящий от немагического оружия» (RAW: Magic Weapons)."""

    def __init__(self, name: str, attack_bonus: int, damage_dice_count: int,
                 damage_dice_type: str, damage_modifier: int, damage_type: str = "",
                 range_ft: int = 5, magical: bool = False):
        self.name = name
        self.attack_bonus = attack_bonus
        self.damage_dice_count = damage_dice_count
        self.damage_dice_type = damage_dice_type
        self.damage_modifier = damage_modifier
        self.damage_type = damage_type
        self.range_ft = range_ft
        self.magical = bool(magical)

    def to_dict(self):
        return {
            'name': self.name,
            'attack_bonus': self.attack_bonus,
            'damage_dice_count': self.damage_dice_count,
            'damage_dice_type': self.damage_dice_type,
            'damage_modifier': self.damage_modifier,
            'damage_type': self.damage_type,
            'range_ft': self.range_ft,
            'magical': self.magical,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            data['name'],
            data['attack_bonus'],
            data['damage_dice_count'],
            data['damage_dice_type'],
            data['damage_modifier'],
            data.get('damage_type', ''),
            data.get('range_ft', 5),
            data.get('magical', False),
        )


class Enemy(Subject):
    """Существо в битве. rng — внедряемая зависимость (DI): None => модульный random."""

    def __init__(self, name: str, hp: int, ac: int, attacks: List[Attack], side: int,
                 regen=0, speed=30, rng=None):
        super().__init__()
        self.name = name
        self.max_hp = hp
        self.hp = hp
        self.ac = ac
        self.attacks = attacks
        self.side = side
        self.alive = True
        self.ignore_sides = set()
        self.strategy: BattleStrategy = RandomStrategy()
        self.regen = regen
        self.speed = speed
        self.pos = None
        self.moved_ft = 0
        self.multiattack = None
        self.ability_scores = {}
        self.ability_mods = {}
        self.saves = {}
        self.skills = {}
        self.senses = {}
        self.vulnerabilities = []
        self.resistances = []
        self.immunities = []
        self.condition_immunities = []
        self.languages = []
        self.cr = None
        self.prof_bonus = None
        self.size = None
        self.type = None
        self.traits = []
        self._rng = rng if rng is not None else random

    def take_damage(self, damage: int):
        actual_damage = max(0, damage)
        previous_hp = self.hp
        self.hp -= actual_damage
        if self.hp <= 0:
            self.alive = False
            self.hp = 0
            self.notify()
            return False
        elif self.hp != previous_hp:
            self.notify()
        return self.alive

    def perform_attack(self, attack: Attack, target_ac: int) -> Tuple[bool, int, int, bool, str]:
        attack_roll = self._rng.randint(1, 20)
        total_attack = attack_roll + attack.attack_bonus
        critical = (attack_roll == 20)
        hit = total_attack >= target_ac or critical
        damage_info = ""
        if hit:
            dice_type = int(attack.damage_dice_type.split('d')[1])
            damage = sum(self._rng.randint(1, dice_type)
                         for _ in range(attack.damage_dice_count)) + attack.damage_modifier
            if critical:
                damage *= 2
            damage = max(0, damage)
            damage_info = f"{damage} урона"
            if attack.damage_type:
                damage_info += f" ({attack.damage_type})"
            if getattr(attack, 'magical', False):
                damage_info += " ✦маг."
            return True, damage, total_attack, critical, damage_info
        return False, 0, total_attack, critical, damage_info

    def regenerate(self):
        if self.alive and self.regen > 0:
            prev_hp = self.hp
            self.hp = min(self.max_hp, self.hp + self.regen)
            if self.hp != prev_hp:
                self.notify()

    def to_dict(self):
        return {
            'name': self.name, 'max_hp': self.max_hp, 'hp': self.hp, 'ac': self.ac,
            'attacks': [a.to_dict() for a in self.attacks],
            'side': self.side, 'alive': self.alive,
            'ignore_sides': list(self.ignore_sides),
            'strategy_type': self.strategy.__class__.__name__,
            'regen': self.regen, 'speed': self.speed, 'pos': self.pos,
            'multiattack': self.multiattack,
            'ability_scores': self.ability_scores, 'ability_mods': self.ability_mods,
            'saves': self.saves, 'skills': self.skills, 'senses': self.senses,
            'vulnerabilities': self.vulnerabilities, 'resistances': self.resistances,
            'immunities': self.immunities, 'condition_immunities': self.condition_immunities,
            'languages': self.languages, 'cr': self.cr, 'prof_bonus': self.prof_bonus,
            'size': self.size, 'type': self.type, 'traits': self.traits,
        }

    @classmethod
    def from_dict(cls, data):
        enemy = cls(data['name'], data['max_hp'], data['ac'],
                    [Attack.from_dict(a) for a in data['attacks']],
                    data['side'], data.get('regen', 0))
        enemy.hp = data['hp']
        enemy.alive = data['alive']
        enemy.ignore_sides = set(data['ignore_sides'])
        enemy.speed = data.get('speed', 30)
        enemy.pos = data.get('pos')
        enemy.multiattack = data.get('multiattack')
        enemy.ability_scores = dict(data.get('ability_scores') or {})
        enemy.ability_mods = dict(data.get('ability_mods') or {})
        enemy.saves = dict(data.get('saves') or {})
        enemy.skills = dict(data.get('skills') or {})
        enemy.senses = dict(data.get('senses') or {})
        enemy.vulnerabilities = list(data.get('vulnerabilities') or [])
        enemy.resistances = list(data.get('resistances') or [])
        enemy.immunities = list(data.get('immunities') or [])
        enemy.condition_immunities = list(data.get('condition_immunities') or [])
        enemy.languages = list(data.get('languages') or [])
        enemy.cr = data.get('cr')
        enemy.prof_bonus = data.get('prof_bonus')
        enemy.size = data.get('size')
        enemy.type = data.get('type')
        enemy.traits = [dict(tr) for tr in (data.get('traits') or [])]

        strategy_type = data.get('strategy_type', 'RandomStrategy')
        from battle_strategies import (AggressiveStrategy, DefensiveStrategy,
                                       RandomStrategy, SupportStrategy)
        enemy.strategy = {
            'AggressiveStrategy': AggressiveStrategy,
            'DefensiveStrategy': DefensiveStrategy,
            'SupportStrategy': SupportStrategy,
        }.get(strategy_type, RandomStrategy)()
        return enemy