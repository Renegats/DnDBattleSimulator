"""Явный запуск Tkinter-фронтенда (страховочный путь на время миграции)."""
import tkinter as tk

from battle_simulator import BattleSimulator


def main():
    root = tk.Tk()
    BattleSimulator(root)
    root.mainloop()


if __name__ == '__main__':
    main()