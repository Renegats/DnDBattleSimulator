import tkinter as tk
from battle_simulator import BattleSimulator

def main():
    """Основная функция запуска приложения"""
    root = tk.Tk()
    app = BattleSimulator(root)
    root.mainloop()

if __name__ == "__main__":
    main()