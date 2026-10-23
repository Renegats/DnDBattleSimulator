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

    def _run_round_inner(self):
        """Проведение одного раунда битвы"""
        if not self.sides or not any(any(enemy.alive for enemy in side) for side in self.sides):
            messagebox.showerror("Ошибка", "Армии не созданы или все мертвы!")
            return

        battle_log = "=== НОВЫЙ РАУНД БОЯ ===\n"

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
                # Используем стратегию для выбора цели
                target = attacker.strategy.select_target(attacker, self.sides,
                                                         self.ignore_sides.get(attacker_side_idx, set()))

                if not target:
                    battle_log += f"{attacker.name} - нет подходящих целей для атаки\n"
                    continue

                # ===== Удары воина: мультиатака (список) или одна атака =====
                strikes = self._resolve_strikes(attacker, target)
                if not strikes:
                    battle_log += f"{attacker.name} - нет доступных атак\n"
                    continue
                reach = self._strike_reach(attacker, strikes)

                # --- Карта: подводимся на дистанцию reach (минимум среди ударов) ---
                if getattr(self, 'battle_map', None) and \
                        self.battle_map.get_pos(attacker) and self.battle_map.get_pos(target):
                    dist = self.battle_map.distance_ft(attacker, target)
                    if dist > reach and getattr(self, 'auto_move', False):
                        self.battle_map.move_towards(attacker, target, attacker.speed,
                                                     reach_ft=reach)
                        dist = self.battle_map.distance_ft(attacker, target)
                    if dist > reach:
                        battle_log += (f"{attacker.name} не может достать {target.name} "
                                       f"({dist} фт > {reach} фт)\n")
                        continue
                    # Воин БЕЗ мультиатаки: после подхода перевыбираем атаку по новой
                    # дистанции (подошёл лучник в упор - пусть рубит мечом, если меч вблизи сильнее)
                    if not getattr(attacker, 'multiattack', None):
                        strikes = self._resolve_strikes(attacker, target)
                        if not strikes:
                            continue

                # ===== Выполнение ударов (мультиатака бьёт по списку) =====
                lines, _killed = self.execute_strikes(attacker, target, strikes)
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

    def _resolve_strikes(self, attacker, target):
        if getattr(attacker, 'multiattack', None):
            by_name = {a.name: a for a in attacker.attacks}
            strikes = []
            for s in attacker.multiattack:
                atk = by_name.get(s['attack'])
                if atk is None:
                    continue                      # имя не распознано парсером - тихо пропускаем
                strikes.extend([atk] * max(1, int(s.get('count', 1))))
            if strikes:
                return strikes
        # нет мультиатаки (или она пустая) - одна атака по стратегии
        a = attacker.strategy.select_attack(attacker, target)
        return [a] if a else []

    def _strike_reach(self, attacker, strikes):
        """Дистанция, на которую надо подойти, чтобы нанести ВСЕ удары = минимум range среди них."""
        if not strikes:
            return 5
        return min(getattr(a, 'range_ft', 5) for a in strikes)

    def _in_range_of(self, attacker, target, atk):
        """Достаёт ли КОНКРЕТНЫЙ удар цель прямо сейчас (страховка внутри мультиатаки)."""
        need = getattr(atk, 'range_ft', 5)
        if getattr(self, 'battle_map', None) and self.battle_map.get_pos(attacker) \
                and self.battle_map.get_pos(target):
            return self.battle_map.distance_ft(attacker, target) <= need
        from battle_strategies import distance_ft_between
        return distance_ft_between(attacker, target) <= need

    def execute_strikes(self, attacker, target, strikes):
        lines, any_killed = [], False
        ignore = self.ignore_sides.get(attacker.side, set())
        for atk in strikes:
            # цель умерла (или изначально не достаётся этой атакой) - ищем новую
            if not target.alive:
                target = self._nearest_in_range(attacker, atk, ignore)
                if target is None:
                    continue  # некого добить этой атакой - удар пропадает
            if not self._in_range_of(attacker, target, atk):
                alt = self._nearest_in_range(attacker, atk, ignore)
                if alt is None:
                    continue
                target = alt
            hit, damage, attack_roll, critical, damage_info = attacker.perform_attack(atk, target.ac)
            if hit:
                target.take_damage(damage)
                crit_text = " КРИТИЧЕСКИЙ УДАР!" if critical else ""
                lines.append(f"{attacker.name} → {target.name} ({atk.name}: "
                             f"{attack_roll} vs AC {target.ac}) - ПОПАДАНИЕ!{crit_text} {damage_info}")
                if not target.alive:
                    lines.append(f"☠️ {target.name} УНИЧТОЖЕН!")
                    any_killed = True  # НЕ break - следующие удары добьют соседей
            else:
                lines.append(f"{attacker.name} → {target.name} ({atk.name}: "
                             f"{attack_roll} vs AC {target.ac}) - ПРОМАХ!")
        return lines, any_killed

    def _nearest_in_range(self, attacker, atk, ignore):
        need = getattr(atk, 'range_ft', 5)
        has_map = getattr(self, 'battle_map', None) is not None \
            and self.battle_map.get_pos(attacker) is not None
        best, best_d = None, None
        for side_idx, side_enemies in enumerate(self.sides):
            if side_idx == attacker.side:
                continue
            if side_idx in ignore or side_idx in attacker.ignore_sides:
                continue
            for e in side_enemies:
                if not e.alive:
                    continue
                if not has_map:
                    return e                      # без карты - любой живой «в радиусе»
                if self.battle_map.get_pos(e) is None:
                    continue
                d = self.battle_map.distance_ft(attacker, e)
                if d <= need and (best_d is None or d < best_d):
                    best, best_d = e, d
        return best