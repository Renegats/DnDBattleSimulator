import tkinter as tk
from tkinter import messagebox

from battle_round import run_round
from combat_core import normalize_crit_mode


class BattleLogic:
    """Класс для управления логикой битвы"""

    def __init__(self, engine):
        """Инициализация логики битвы."""
        self.engine = engine

    def _run_round_inner(self):
        """Проведение одного раунда битвы. Расчёт — в battle_round.run_round."""
        if hasattr(self, 'crit_mode_var'):
            self.crit_damage_mode = normalize_crit_mode(self.crit_mode_var.get())
        outcome, text = run_round(
            self.sides,
            getattr(self, 'side_names', []),
            getattr(self, 'ignore_sides', {}),
            getattr(self, 'battle_map', None),
            self.engine,
            auto_move=getattr(self, 'auto_move', False),
            crit_mode=normalize_crit_mode(getattr(self, 'crit_damage_mode', 'double_all')),
        )
        if outcome == 'empty':
            messagebox.showerror("Ошибка", text)
            return

        widget = getattr(self, 'battle_results_text', None)
        if widget is None:
            return
        widget.insert(tk.END, text + "\n")
        widget.see(tk.END)
        if int(widget.index('end-1c').split('.')[0]) > 3000:
            widget.delete('1.0', 'end-2500l')

    def run_battle_round(self):
        self.ui_suspend = True
        try:
            self._run_round_inner()
        finally:
            self.ui_suspend = False
            self.update_battle_ui()
            if getattr(self, 'battle_map', None):
                self.draw_map()