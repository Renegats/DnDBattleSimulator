from entities import Enemy, Attack


class EnemyFactory:
    """Фабрика для создания врагов разных типов"""
    CUSTOM_TYPES = {}  # Сюда импортер из бестиария регистрирует монстров с dnd.su

    @staticmethod
    def register_type(type_name, hp, ac, attacks, speed=30, regen=0):
        """Регистрация кастомного монстра (атаки - список словарей для Attack(**a))"""
        EnemyFactory.CUSTOM_TYPES[type_name] = {
            'hp': hp, 'ac': ac, 'attacks': attacks, 'speed': speed, 'regen': regen
        }

    @staticmethod
    def create_enemy(enemy_type, name, side):
        # Сначала ищем импортированного монстра!
        if enemy_type in EnemyFactory.CUSTOM_TYPES:
            t = EnemyFactory.CUSTOM_TYPES[enemy_type]
            return Enemy(name=name, hp=t['hp'], ac=t['ac'],
                         attacks=[Attack(**a) for a in t['attacks']],
                         side=side, regen=t['regen'], speed=t['speed'])
        if enemy_type == "гоблин":
            return Enemy(
                name=name,
                hp=7,
                ac=14,
                attacks=[
                    Attack("Короткий меч", 4, 1, "d6", 2),
                    Attack("Короткий лук", 4, 1, "d6", 2, "колющий")
                ],
                side=side
            )
        elif enemy_type == "орк":
            return Enemy(
                name=name,
                hp=15,
                ac=13,
                attacks=[
                    Attack("Большой топор", 5, 1, "d12", 3, "рубящий")
                ],
                side=side
            )
        elif enemy_type == "скелет":
            return Enemy(
                name=name,
                hp=13,
                ac=16,
                attacks=[
                    Attack("Длинный меч", 4, 1, "d8", 2, "рубящий"),
                    Attack("Короткий лук", 4, 1, "d6", 2, "колющий")
                ],
                side=side
            )
        elif enemy_type == "тролль":
            return Enemy(
                name=name,
                hp=84,
                ac=15,
                attacks=[
                    Attack("Когти", 7, 2, "d6", 3, "дробящий"),
                    Attack("Укус", 7, 2, "d6", 3, "пронзающий")
                ],
                side=side,
                regen=10
            )
        elif enemy_type == "гном":
            return Enemy(
                name=name,
                hp=10,
                ac=16,
                attacks=[
                    Attack("Молоток", 3, 1, "d6", 1, "дробящий"),
                    Attack("Праща", 3, 1, "d4", 1, "дробящий")
                ],
                side=side
            )
        elif enemy_type == "эльф":
            return Enemy(
                name=name,
                hp=12,
                ac=15,
                attacks=[
                    Attack("Длинный меч", 4, 1, "d8", 2, "рубящий"),
                    Attack("Длинный лук", 6, 1, "d8", 2, "колющий")
                ],
                side=side
            )
        elif enemy_type == "дротик":
            return Enemy(
                name=name,
                hp=22,
                ac=13,
                attacks=[
                    Attack("Укус", 4, 1, "d6", 2, "пронзающий"),
                    Attack("Огненное дыхание", 0, 3, "d6", 0, "огневой")
                ],
                side=side
            )
        else:  # тип по умолчанию
            return Enemy(
                name=name,
                hp=10,
                ac=10,
                attacks=[
                    Attack("Атака", 0, 1, "d6", 0)
                ],
                side=side
            )