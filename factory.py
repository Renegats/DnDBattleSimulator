import logging

from entities import Enemy, Attack

logger = logging.getLogger(__name__)


def _creature_def(hp, ac, attacks, speed=30, regen=0, multiattack=None, *,
                  ability_scores=None, ability_mods=None, saves=None, skills=None,
                  senses=None, vulnerabilities=None, resistances=None, immunities=None,
                  condition_immunities=None, languages=None, cr=None, prof_bonus=None,
                  size=None, ctype=None, traits=None):
    """Конструктор записи реестра с дефолтами по схеме (чтобы не писать {} / [] везде).
    Боевые поля обязательны; справочные опциональны — отсутствие = пустой контейнер/None."""
    return {
        'hp': hp, 'ac': ac, 'attacks': attacks, 'speed': speed, 'regen': regen,
        'multiattack': multiattack,
        'ability_scores': ability_scores or {}, 'ability_mods': ability_mods or {},
        'saves': saves or {}, 'skills': skills or {}, 'senses': senses or {},
        'vulnerabilities': vulnerabilities or [], 'resistances': resistances or [],
        'immunities': immunities or [], 'condition_immunities': condition_immunities or [],
        'languages': languages or [], 'cr': cr, 'prof_bonus': prof_bonus,
        'size': size, 'type': ctype, 'traits': traits or [],
    }


class EnemyFactory:
    """Фабрика для создания врагов разных типов"""
    CUSTOM_TYPES = {}    # импортированные/кастомные
    CREATURE_DEFS = {}   # канонические встроенные типы

    CREATURE_DEFS = {
        'обычный': _creature_def(hp=10, ac=10, speed=30,
            attacks=[{'name': 'Атака', 'attack_bonus': 0, 'damage_dice_count': 1,
                      'damage_dice_type': 'd6', 'damage_modifier': 0, 'damage_type': ''}]),

        'гоблин': _creature_def(hp=7, ac=14, speed=30,
            attacks=[{'name': 'Короткий меч', 'attack_bonus': 4, 'damage_dice_count': 1,
                      'damage_dice_type': 'd6', 'damage_modifier': 2, 'damage_type': 'рубящий'},
                     {'name': 'Короткий лук', 'attack_bonus': 4, 'damage_dice_count': 1,
                      'damage_dice_type': 'd6', 'damage_modifier': 2, 'damage_type': 'колющий',
                      'range_ft': 80}],
            ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8},
            ability_mods={'str': -1, 'dex': 2, 'con': 0, 'int': 0, 'wis': -1, 'cha': -1},
            skills={'Скрытность': '+4', 'Восприятие': '+1'},
            senses={'Тёмное зрение': '60', 'Пассивное восприятие': '11'},
            languages=['общий', 'гоблинский'], cr='1/4', prof_bonus='+2',
            size='Малый', ctype='гуманоид (гоблиноид)',
            traits=[{'name': 'Ловкое ускользание',
                     'desc': 'Бонусным действием может отступить (Disengage) или спрятаться (Hide).'}]),

        'орк': _creature_def(hp=15, ac=13, speed=30,
            attacks=[{'name': 'Большой топор', 'attack_bonus': 5, 'damage_dice_count': 1,
                      'damage_dice_type': 'd12', 'damage_modifier': 3, 'damage_type': 'рубящий'}],
            ability_scores={'str': 16, 'dex': 12, 'con': 16, 'int': 7, 'wis': 11, 'cha': 10},
            ability_mods={'str': 3, 'dex': 1, 'con': 3, 'int': -2, 'wis': 0, 'cha': 0},
            skills={'Устрашение': '+2'},
            senses={'Тёмное зрение': '60', 'Пассивное восприятие': '10'},
            languages=['общий', 'безымянный'], cr='1/2', prof_bonus='+2',
            size='Средний', ctype='гуманоид (орк)',
            traits=[{'name': 'Ярость орка',
                     'desc': 'Когда HP падает до 0, но существо не умирает, может потратить реакцию, чтобы остаться с 1 HP.'}]),

        'скелет': _creature_def(hp=13, ac=16, speed=30,
            attacks=[{'name': 'Длинный меч', 'attack_bonus': 4, 'damage_dice_count': 1,
                      'damage_dice_type': 'd8', 'damage_modifier': 2, 'damage_type': 'рубящий'},
                     {'name': 'Короткий лук', 'attack_bonus': 4, 'damage_dice_count': 1,
                      'damage_dice_type': 'd6', 'damage_modifier': 2, 'damage_type': 'колющий',
                      'range_ft': 80}],
            ability_scores={'str': 10, 'dex': 14, 'con': 0, 'int': 6, 'wis': 8, 'cha': 7},
            ability_mods={'str': 0, 'dex': 2, 'con': 0, 'int': -2, 'wis': -1, 'cha': -2},
            senses={'Тёмное зрение': '60', 'Пассивное восприятие': '9'},
            vulnerabilities=['дробящий'], immunities=['некротический', 'яд'],
            condition_immunities=['истощение', 'отравление'],
            cr='1/4', prof_bonus='+2', size='Средний', ctype='нежить'),

        'тролль': _creature_def(hp=84, ac=15, speed=30, regen=10,
            attacks=[{'name': 'Когти', 'attack_bonus': 7, 'damage_dice_count': 2,
                      'damage_dice_type': 'd6', 'damage_modifier': 3, 'damage_type': 'дробящий'},
                     {'name': 'Укус', 'attack_bonus': 7, 'damage_dice_count': 2,
                      'damage_dice_type': 'd6', 'damage_modifier': 3, 'damage_type': 'пронзающий'}],
            multiattack=[{'attack': 'Когти', 'count': 2}, {'attack': 'Укус', 'count': 1}],
            ability_scores={'str': 18, 'dex': 13, 'con': 20, 'int': 7, 'wis': 9, 'cha': 7},
            ability_mods={'str': 4, 'dex': 1, 'con': 5, 'int': -2, 'wis': -1, 'cha': -2},
            senses={'Тёмное зрение': '60', 'Пассивное восприятие': '9'},
            languages=['великанский'], vulnerabilities=['огонь', 'холод'],
            cr='5', prof_bonus='+3', size='Огромный', ctype='гигант',
            traits=[{'name': 'Острый нюх',
                     'desc': 'Преимущество на проверки Восприятия, основанные на обонянии.'},
                    {'name': 'Регенерация',
                     'desc': 'В начале хода восстанавливает 10 HP, если с прошлого хода не получил урон огнём или кислотой.'}]),

        'гном': _creature_def(hp=10, ac=16, speed=25,
            attacks=[{'name': 'Молоток', 'attack_bonus': 3, 'damage_dice_count': 1,
                      'damage_dice_type': 'd6', 'damage_modifier': 1, 'damage_type': 'дробящий'},
                     {'name': 'Праща', 'attack_bonus': 3, 'damage_dice_count': 1,
                      'damage_dice_type': 'd4', 'damage_modifier': 1, 'damage_type': 'дробящий',
                      'range_ft': 30}],
            # справочные значения-заглушка: в ММ «гном» — раса, не отдельный монстр; допишем этапом 2
            ability_scores={'str': 9, 'dex': 13, 'con': 14, 'int': 12, 'wis': 10, 'cha': 9},
            ability_mods={'str': -1, 'dex': 1, 'con': 2, 'int': 1, 'wis': 0, 'cha': -1},
            senses={'Тёмное зрение': '60', 'Пассивное восприятие': '10'},
            languages=['общий', 'гномий'], cr='1/4', prof_bonus='+2',
            size='Малый', ctype='гуманоид (гном)'),

        'эльф': _creature_def(hp=12, ac=15, speed=30,
            attacks=[{'name': 'Длинный меч', 'attack_bonus': 4, 'damage_dice_count': 1,
                      'damage_dice_type': 'd8', 'damage_modifier': 2, 'damage_type': 'рубящий'},
                     {'name': 'Длинный лук', 'attack_bonus': 6, 'damage_dice_count': 1,
                      'damage_dice_type': 'd8', 'damage_modifier': 2, 'damage_type': 'колющий',
                      'range_ft': 150}],
            ability_scores={'str': 10, 'dex': 14, 'con': 10, 'int': 12, 'wis': 11, 'cha': 10},
            ability_mods={'str': 0, 'dex': 2, 'con': 0, 'int': 1, 'wis': 0, 'cha': 0},
            senses={'Тёмное зрение': '60', 'Пассивное восприятие': '10'},
            languages=['общий', 'эльфийский'], cr='1/4', prof_bonus='+2',
            size='Средний', ctype='гуманоид (эльф)'),

        'дротик': _creature_def(hp=22, ac=13, speed=30,
            attacks=[{'name': 'Укус', 'attack_bonus': 4, 'damage_dice_count': 1,
                      'damage_dice_type': 'd6', 'damage_modifier': 2, 'damage_type': 'пронзающий'},
                     {'name': 'Огненное дыхание', 'attack_bonus': 0, 'damage_dice_count': 3,
                      'damage_dice_type': 'd6', 'damage_modifier': 0, 'damage_type': 'огневой',
                      'range_ft': 15}],
            ability_scores={'str': 14, 'dex': 12, 'con': 14, 'int': 6, 'wis': 10, 'cha': 10},
            ability_mods={'str': 2, 'dex': 1, 'con': 2, 'int': -2, 'wis': 0, 'cha': 0},
            senses={'Тёмное зрение': '60', 'Пассивное восприятие': '10'},
            languages=[], cr='1', prof_bonus='+2', size='Средний', ctype='дракон'),
    }

    @staticmethod
    def register_type(type_name, hp, ac, attacks, speed=30, regen=0, multiattack=None, **extra):
        EnemyFactory.CUSTOM_TYPES[type_name] = {
            'hp': hp, 'ac': ac, 'attacks': attacks,
            'speed': speed, 'regen': regen,
            'multiattack': multiattack,
            **extra,
        }

    @staticmethod
    def _make_attack(data):
        """Создаёт Attack из словаря, аккуратно вынимая range_ft"""
        data = dict(data)
        range_ft = data.pop('range_ft', 5)
        attack = Attack(**data)
        attack.range_ft = range_ft
        return attack

    @staticmethod
    def _finish(enemy, speed=30, ranges=()):
        """Гарантирует speed; range_ft уже проставлен _make_attack из dict реестра,
        поэтому ranges здесь больше не нужен (оставлен для совместимости сигнатуры)."""
        enemy.speed = speed
        for idx, attack in enumerate(enemy.attacks):
            attack.range_ft = ranges[idx] if idx < len(ranges) else getattr(attack, 'range_ft', 5)
        return enemy

    @staticmethod
    def _apply_def(enemy, t):
        """МОСТ между схемой реестра и объектом Enemy: проставляет ВСЕ справочные поля
        с дефолтами. Единая точка для CREATURE_DEFS и CUSTOM_TYPES — поэтому парсер
        (этап 1) и форма (этап 3), наполняющие dict, подхватятся без правок фабрики."""
        enemy.ability_scores = dict(t.get('ability_scores') or {})
        enemy.ability_mods = dict(t.get('ability_mods') or {})
        enemy.saves = dict(t.get('saves') or {})
        enemy.skills = dict(t.get('skills') or {})
        enemy.senses = dict(t.get('senses') or {})
        enemy.vulnerabilities = list(t.get('vulnerabilities') or [])
        enemy.resistances = list(t.get('resistances') or [])
        enemy.immunities = list(t.get('immunities') or [])
        enemy.condition_immunities = list(t.get('condition_immunities') or [])
        enemy.languages = list(t.get('languages') or [])
        enemy.cr = t.get('cr')
        enemy.prof_bonus = t.get('prof_bonus')
        enemy.size = t.get('size')
        enemy.type = t.get('type')
        enemy.traits = [dict(tr) for tr in (t.get('traits') or [])]
        return enemy

    @staticmethod
    def create_enemy(enemy_type, name, side, registry=None):
        reg = registry if registry is not None else PRODUCTION_REGISTRY
        t = reg.lookup(enemy_type)
        enemy = Enemy(name=name, hp=t['hp'], ac=t['ac'],
                      attacks=[EnemyFactory._make_attack(a) for a in t['attacks']],
                      side=side, regen=t.get('regen', 0))
        enemy = EnemyFactory._finish(enemy, speed=t.get('speed', 30))
        enemy.multiattack = t.get('multiattack')
        EnemyFactory._apply_def(enemy, t)
        return enemy


class CreatureRegistry:
    def __init__(self, defs=None, custom=None):
        self.defs = defs if defs is not None else {}
        self.custom = custom if custom is not None else {}

    def lookup(self, type_name):
        if type_name in self.custom:
            return self.custom[type_name]
        if type_name in self.defs:
            return self.defs[type_name]
        logger.warning(
            "Неизвестный тип существа %r — используется «обычный»", type_name)
        return self.defs.get('обычный')

    def register(self, type_name, **data):
        self.custom[type_name] = data

PRODUCTION_REGISTRY = CreatureRegistry(
    defs=EnemyFactory.CREATURE_DEFS,
    custom=EnemyFactory.CUSTOM_TYPES,
)