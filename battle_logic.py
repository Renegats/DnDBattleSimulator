import random
import tkinter as tk
from tkinter import ttk, messagebox
from entities import Enemy
from battle_strategies import BattleStrategy, RandomStrategy, AggressiveStrategy, DefensiveStrategy, SupportStrategy


class BattleLogic:
    """Класс для управления логикой битвы"""

    def __init__(self):
        """Инициализация логики битвы"""
        pass

    def run_battle_round(self):
        """Проведение одного раунда битвы"""
        if not self.sides or not any(any(enemy.alive for enemy in side) for side in self.sides):
            messagebox.showerror("Ошибка", "Армии не созданы или все мертвы!")
            return

        battle_log = "=== НОВЫЙ РАУНД БОЯ ===\n"

        # Новый раунд - все очки движения восстанавливаются
        for side_enemies in self.sides:
            for enemy in side_enemies:
                enemy.moved_ft = 0

        # Обработка атак для каждой стороны
        for attacker_side_idx, side_enemies in enumerate(self.sides):
            alive_attackers = [e for e in side_enemies if e.alive]
            for attacker in alive_attackers:
                # Используем стратегию для выбора цели
                target = attacker.strategy.select_target(attacker, self.sides,
                                                         self.ignore_sides.get(attacker_side_idx, set()))

                if not target:
                    battle_log += f"{attacker.name} - нет подходящих целей для атаки\n"
                    continue

                # Используем стратегию для выбора атаки
                attack = attacker.strategy.select_attack(attacker, target)
                if not attack:
                    # Если стратегия не выбрала атаку, выбираем случайную из доступных
                    if attacker.attacks:
                        attack = random.choice(attacker.attacks)
                    else:
                        attack = None

                if not attack:
                    battle_log += f"{attacker.name} - нет доступных атак\n"
                    continue

                # --- Карта: продвижение к цели и проверка дальности ---
                if getattr(self, 'battle_map', None) and \
                        self.battle_map.get_pos(attacker) and self.battle_map.get_pos(target):
                    dist = self.battle_map.distance_ft(attacker, target)
                    if dist > attack.range_ft and getattr(self, 'auto_move', False):
                        self.battle_map.move_towards(attacker, target, attacker.speed)
                        dist = self.battle_map.distance_ft(attacker, target)
                    if dist > attack.range_ft:
                        battle_log += (f"{attacker.name} не может достать {target.name} "
                                       f"({dist} фт > {attack.range_ft} фт)\n")
                        continue

                # Выполнение атаки
                hit, damage, attack_roll, critical, damage_info = attacker.perform_attack(attack, target.ac)
                if hit:
                    target.take_damage(damage)
                    crit_text = " КРИТИЧЕСКИЙ УДАР!" if critical else ""
                    battle_log += f"{attacker.name} → {target.name} ({attack.name}: {attack_roll} vs AC {target.ac}) - ПОПАДАНИЕ!{crit_text} {damage_info}\n"
                    if not target.alive:
                        battle_log += f"☠️ {target.name} УНИЧТОЖЕН!\n"
                else:
                    battle_log += f"{attacker.name} → {target.name} ({attack.name}: {attack_roll} vs AC {target.ac}) - ПРОМАХ!\n"

            battle_log += "\n"

        # Фаза регенерации для существ с особой способностью
        for side_enemies in self.sides:
            for enemy in side_enemies:
                if enemy.alive and enemy.regen > 0:
                    prev_hp = enemy.hp
                    enemy.regenerate()
                    if enemy.hp > prev_hp:
                        battle_log += f"💚 {enemy.name} восстанавливает {enemy.hp - prev_hp} HP благодаря регенерации\n"

        # Проверка исхода битвы
        alive_sides = []
        for i, side_enemies in enumerate(self.sides):
            if any(enemy.alive for enemy in side_enemies):
                alive_sides.append(self.side_names[i])

        if len(alive_sides) <= 1:
            if alive_sides:
                battle_log += f"\n🎉 {alive_sides[0]} ПОБЕДИЛА!\n"
            else:
                battle_log += f"\n⚔️ Все стороны уничтожены! Ничья.\n"
        else:
            battle_log += f"\nБитва продолжается: {' vs '.join(alive_sides)}\n"

        # Вставляем результаты в текстовое поле
        if hasattr(self, 'battle_results_text'):
            self.battle_results_text.insert(tk.END, battle_log + "\n")

        self.battle_results_text.see(tk.END)

        # Обновляем UI чтобы показать изменения в здоровье
        self.update_battle_ui()
        if getattr(self, 'battle_map', None):
            self.draw_map()