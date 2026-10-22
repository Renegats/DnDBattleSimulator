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
            army_types = [var.get() for var in self.army_type_vars[:self.num_sides_var.get()]]
            strategy_types = [var.get() for var in self.strategy_type_vars[:self.num_sides_var.get()]]

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
        """Загрузка настроек из файла"""
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

            # Применение настроек
            self.num_sides_var.set(settings['num_sides'])
            self.update_sides_ui()
            self.update_types_ui()

            for i in range(len(self.side_name_vars)):
                if i < len(settings.get('side_names', [])):
                    self.side_name_vars[i].set(settings['side_names'][i])
                if i < len(settings.get('side_counts', [])):
                    self.side_count_vars[i].set(settings['side_counts'][i])

            # восстанавливаем импортированных монстров ДО создания армий!
            from factory import EnemyFactory
            if not hasattr(EnemyFactory, 'CUSTOM_TYPES'):
                EnemyFactory.CUSTOM_TYPES = {}

            restored_custom = settings.get('custom_types', {})
            for type_name, type_data in restored_custom.items():
                EnemyFactory.CUSTOM_TYPES[type_name] = type_data
                # Добавляем имя типа в список, чтобы он появился во всех combobox!
                if type_name not in self.enemy_types:
                    self.enemy_types.append(type_name)

            # Обновляем значения во всех существующих combobox
            for combo in self.army_type_vars:
                current_value = combo.get()
                combo.set('')  # сбрасываем
                combo.set(current_value)  # и восстанавливаем (теперь тип есть в списке!)

            # Загрузка типов армий и стратегий
            if 'army_types' in settings:
                for i, army_type in enumerate(settings['army_types']):
                    if i < len(self.army_type_vars):
                        self.army_type_vars[i].set(army_type)

            if 'strategy_types' in settings:
                for i, strategy_type in enumerate(settings['strategy_types']):
                    if i < len(self.strategy_type_vars):
                        self.strategy_type_vars[i].set(strategy_type)

            # Загрузка настроек альянсов если они существуют
            if 'alliance_settings' in settings:
                self.alliance_settings = settings['alliance_settings']

            # Загрузка глобальных настроек игнорирования
            if 'ignore_sides' in settings:
                self.ignore_sides = {int(k): set(v) for k, v in settings['ignore_sides'].items()}
            # Обновляем список значений во всех combobox-ах армий
            for var in self.army_type_vars:
                # Ищем combobox через родительский виджет
                for child in self.types_frame.winfo_children():
                    for widget in child.winfo_children():
                        if isinstance(widget, ttk.Combobox) and widget.cget('textvariable') == var:
                            widget.config(values=self.enemy_types)
            messagebox.showinfo("Успех", "Настройки загружены!")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при загрузке: {str(e)}")