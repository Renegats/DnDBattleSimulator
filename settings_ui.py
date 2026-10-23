import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
from datetime import datetime
from entities import Attack, Enemy
from battle_strategies import AggressiveStrategy, DefensiveStrategy, RandomStrategy, SupportStrategy


class SettingsUI:
    """Класс для управления настройками и сохранением/загрузкой"""

    def __init__(self):
        """Инициализация UI настроек"""
        pass

    def save_settings(self):
        """Сохранение текущих настроек в файл"""
        try:
            # Создание директории для настроек если она не существует
            if not os.path.exists('battle_settings'):
                os.makedirs('battle_settings')

            # Генерация имени файла с временной меткой
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"battle_settings/battle_{timestamp}.json"

            # Сохраняем текущие настройки альянсов
            current_alliance_settings = []
            if hasattr(self, 'alliance_vars'):
                for i in range(len(self.alliance_vars)):
                    row_settings = []
                    for j in range(len(self.alliance_vars[i])):
                        if self.alliance_vars[i][j] is not None:
                            row_settings.append(self.alliance_vars[i][j].get())
                        else:
                            row_settings.append(False)
                    current_alliance_settings.append(row_settings)

            # Сохраняем типы армий и стратегии
            army_types = list(self.side_army_types[:self.num_sides_var.get()])
            strategy_types = [v.get() for v in self.side_strategy_vars[:self.num_sides_var.get()]]

            from factory import EnemyFactory
            custom_types_snapshot = dict(getattr(EnemyFactory, 'CUSTOM_TYPES', {}))

            settings = {
                'num_sides': self.num_sides_var.get(),
                'side_names': [var.get() for var in self.side_name_vars],
                'side_counts': [var.get() for var in self.side_count_vars],
                'army_types': army_types,
                'strategy_types': strategy_types,
                'custom_types': custom_types_snapshot,
                'alliance_settings': current_alliance_settings if current_alliance_settings else self.alliance_settings,
                'ignore_sides': {str(k): list(v) for k, v in self.ignore_sides.items()} if hasattr(self,
                                                                                                   'ignore_sides') else {}
            }

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("Успех", f"Настройки сохранены в файл:\n{filename}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при сохранении: {str(e)}")

    def load_settings(self):
        """Загрузка настроек из файла (под новую архитектуру карточек сторон)"""
        try:
            filename = filedialog.askopenfilename(
                title="Выберите файл настроек",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                initialdir="battle_settings"
            )
            if not filename:
                return

            with open(filename, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            from factory import EnemyFactory
            if not hasattr(EnemyFactory, 'CUSTOM_TYPES'):
                EnemyFactory.CUSTOM_TYPES = {}
            for type_name, type_data in settings.get('custom_types', {}).items():
                EnemyFactory.CUSTOM_TYPES[type_name] = type_data
                if type_name not in self.enemy_types:
                    self.enemy_types.append(type_name)

            for frame in self.side_frames:
                frame.destroy()
            for lst in (self.side_frames, self.side_name_vars, self.side_count_vars,
                        self.side_army_types, self.side_strategy_vars, self.side_type_labels):
                lst.clear()


            saved_names   = settings.get('side_names', [])
            saved_counts  = settings.get('side_counts', [])
            saved_types   = settings.get('army_types', [])
            saved_strats  = settings.get('strategy_types', [])
            num_sides     = int(settings.get('num_sides', 0))

            for i in range(num_sides):
                army_type = saved_types[i] if i < len(saved_types) else self.enemy_types[0]
                strategy  = saved_strats[i] if i < len(saved_strats) else self.strategy_types[0]
                name      = saved_names[i] if i < len(saved_names) else None
                count     = saved_counts[i] if i < len(saved_counts) else None
                self._create_new_side(army_type, strategy, name=name, count=count)

            # Синхронизируем внутренний счётчик сторон (нужен вкладке альянсов позже).
            self.num_sides = num_sides

            if 'alliance_settings' in settings:
                self.alliance_settings = settings['alliance_settings']
            if 'ignore_sides' in settings:
                self.ignore_sides = {int(k): set(v) for k, v in settings['ignore_sides'].items()}

            messagebox.showinfo("Успех", f"Настройки загружены!\nСторон восстановлено: {num_sides}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при загрузке: {str(e)}")