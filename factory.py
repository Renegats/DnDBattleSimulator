from entities import Enemy, Attack


class EnemyFactory:
    """Фабрика для создания врагов разных типов"""
    CUSTOM_TYPES = {}  # Сюда регистрируются монстры, импортированные с dnd.su

    @staticmethod
    def register_type(type_name, hp, ac, attacks, speed=30, regen=0):
        """Регистрация кастомного монстра; attacks - список словарей с ключами Attack"""
        EnemyFactory.CUSTOM_TYPES[type_name] = {
            'hp': hp,
            'ac': ac,
            'attacks': attacks,
            'speed': speed,
            'regen': regen,
        }

    @staticmethod
    def _make_attack(data):
        """Создаёт Attack из словаря, аккуратно вынимая range_ft"""
        data = dict(data)
        range_ft = data.pop('range_ft', 5)
        attack = Attack(**data)
        attack.range_ft = range_ft  # дальность: 5/10 рукопашка, 80/150 луки
        return attack

    @staticmethod
    def _finish(enemy, speed=30, ranges=()):
        """Гарантирует, что у врага есть speed, а у каждой атаки - range_ft"""
        enemy.speed = speed
        for idx, attack in enumerate(enemy.attacks):
            attack.range_ft = ranges[idx] if idx < len(ranges) else getattr(attack, 'range_ft', 5)
        return enemy

    @staticmethod
    def create_enemy(enemy_type, name, side):
        """Создает врага определенного типа с предопределенными характеристиками"""
        # 1) Сначала ищем среди импортированных монстров с dnd.su!
        if enemy_type in EnemyFactory.CUSTOM_TYPES:
            t = EnemyFactory.CUSTOM_TYPES[enemy_type]
            enemy = Enemy(
                name=name,
                hp=t['hp'],
                ac=t['ac'],
                attacks=[EnemyFactory._make_attack(a) for a in t['attacks']],
                side=side,
                regen=t.get('regen', 0)
            )
            return EnemyFactory._finish(enemy, speed=t.get('speed', 30))

        # 2) Встроенные типы
        if enemy_type == "гоблин":
            return EnemyFactory._finish(Enemy(
                name=name, hp=7, ac=14,
                attacks=[Attack("Короткий меч", 4, 1, "d6", 2),
                         Attack("Короткий лук", 4, 1, "d6", 2, "колющий")],
                side=side), speed=30, ranges=(5, 80))
        elif enemy_type == "орк":
            return EnemyFactory._finish(Enemy(
                name=name, hp=15, ac=13,
                attacks=[Attack("Большой топор", 5, 1, "d12", 3, "рубящий")],
                side=side), speed=30)
        elif enemy_type == "скелет":
            return EnemyFactory._finish(Enemy(
                name=name, hp=13, ac=16,
                attacks=[Attack("Длинный меч", 4, 1, "d8", 2, "рубящий"),
                         Attack("Короткий лук", 4, 1, "d6", 2, "колющий")],
                side=side), speed=30, ranges=(5, 80))
        elif enemy_type == "тролль":
            return EnemyFactory._finish(Enemy(
                name=name, hp=84, ac=15,
                attacks=[Attack("Когти", 7, 2, "d6", 3, "дробящий"),
                         Attack("Укус", 7, 2, "d6", 3, "пронзающий")],
                side=side, regen=10), speed=30)
        elif enemy_type == "гном":
            return EnemyFactory._finish(Enemy(
                name=name, hp=10, ac=16,
                attacks=[Attack("Молоток", 3, 1, "d6", 1, "дробящий"),
                         Attack("Праща", 3, 1, "d4", 1, "дробящий")],
                side=side), speed=25, ranges=(5, 30))
        elif enemy_type == "эльф":
            return EnemyFactory._finish(Enemy(
                name=name, hp=12, ac=15,
                attacks=[Attack("Длинный меч", 4, 1, "d8", 2, "рубящий"),
                         Attack("Длинный лук", 6, 1, "d8", 2, "колющий")],
                side=side), speed=30, ranges=(5, 150))
        elif enemy_type == "дротик":
            return EnemyFactory._finish(Enemy(
                name=name, hp=22, ac=13,
                attacks=[Attack("Укус", 4, 1, "d6", 2, "пронзающий"),
                         Attack("Огненное дыхание", 0, 3, "d6", 0, "огневой")],
                side=side), speed=30, ranges=(5, 15))
        else:  # тип по умолчанию
            return EnemyFactory._finish(Enemy(
                name=name, hp=10, ac=10,
                attacks=[Attack("Атака", 0, 1, "d6", 0)],
                side=side), speed=30)