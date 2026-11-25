import random
import tkinter as tk
from tkinter import ttk, messagebox
from entities import Enemy
from battle_strategies import BattleStrategy, RandomStrategy, AggressiveStrategy, DefensiveStrategy, SupportStrategy
from combat_core import resolve_strikes, strike_reach, execute_strikes


class BattleLogic:
    """Класс для управления логикой битвы"""

    def __init__(self, engine):
        """Инициализация логики битвы."""
        self.engine = engine

    def _run_round_inner(self):
        """Проведение одного раунда битвы"""
        if not self.sides or not any(any(enemy.alive for enemy in side) for side in self.sides):
            messagebox.showerror("Ошибка", "Армии не созданы или все мертвы!")
            return

        battle_log = "=== НОВЫЙ РАУНД БОЯ ===\n"
        self.engine.begin_round()  # сброс журнала объяснений на новый раунд (СПР-анализ)

        # Новый раунд - все очки движения восстанавливаются
        for side_enemies in self.sides:
            for enemy in side_enemies:
                enemy.moved_ft = 0

        if getattr(self, 'battle_map', None):
            for side_enemies in self.sides:
                for enemy in side_enemies:
                    real = self.battle_map.get_pos(enemy)
                    if real is not None:
                        enemy.pos = real

        # Обработка атак для каждой стороны
        for attacker_side_idx, side_enemies in enumerate(self.sides):
            alive_attackers = [e for e in side_enemies if e.alive]
            for attacker in alive_attackers:
                # ===== v1 ИИ: мозг решает цель/атаку/намерение движения =====
                decision = self.engine.decide(attacker, self.sides,
                                              self.ignore_sides.get(attacker_side_idx, set()))
                target = decision.target
                if not target:
                    battle_log += f"{attacker.name} - нет подходящих целей для атаки\n"
                    continue
                if decision.rationale:
                    battle_log += f"🧠 {attacker.name}: {decision.rationale}\n"

                if decision.attack is None:
                    # делегат (tier0/1) или мультиатака - старый путь развёртки
                    strikes = resolve_strikes(attacker, target)
                    if not strikes:
                        battle_log += f"{attacker.name} - нет доступных атак\n"
                        continue
                    reach = strike_reach(strikes)
                else:
                    # smart-одиночная (tier>=2): атака уже выбрана с учётом защиты/дальности
                    strikes = [decision.attack]
                    reach = decision.target_dist_ft

                # --- Карта: движение по move_intent (approach / hold) ---
                if getattr(self, 'battle_map', None) and \
                        self.battle_map.get_pos(attacker) and self.battle_map.get_pos(target):
                    dist = self.battle_map.distance_ft(attacker, target)
                    if decision.move_intent == 'hold' and dist <= reach:
                        pass  # держим дистанцию: уже достаём, не подбегаем (v1 C2-half)
                    elif dist > reach and getattr(self, 'auto_move', False):
                        self.battle_map.move_towards(attacker, target, attacker.speed,
                                                     reach_ft=reach)
                        dist = self.battle_map.distance_ft(attacker, target)
                    if dist > reach:
                        battle_log += (f"{attacker.name} не может достать {target.name} "
                                       f"({dist} фт > {reach} фт)\n")
                        continue
                    # перевыбор ДЛЯ ДЕЛЕГАТ-ОДИНОЧНЫХ (tier<=1): старый цикл после подхода
                    # переспрашивал стратегию по новой дистанции - сохраняем ноль регрессии.
                    if decision.attack is None and decision.tier <= 1 \
                            and not getattr(attacker, 'multiattack', None):
                        strikes = resolve_strikes(attacker, target)
                        if not strikes:
                            continue

                # ===== Выполнение ударов =====
                lines, _killed = execute_strikes(attacker, target, strikes,
                                                 self.sides, self.ignore_sides,
                                                 getattr(self, 'battle_map', None))
                for ln in lines:
                    battle_log += ln + "\n"

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
        if int(self.battle_results_text.index('end-1c').split('.')[0]) > 3000:
            self.battle_results_text.delete('1.0', 'end-2500l')

    def run_battle_round(self):
        self.ui_suspend = True
        try:
            self._run_round_inner()
        finally:
            self.ui_suspend = False
            self.update_battle_ui()
            if getattr(self, 'battle_map', None):
                self.draw_map()