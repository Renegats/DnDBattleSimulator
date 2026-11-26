"""История отмены боя. Без привязки к интерфейсу.

Снимок — обычный словарь, который можно положить в JSON. Отмена возвращает
снимок «до», повтор — сохранённый снимок «после», без нового броска костей.
Живые объекты существ по возможности те же самые: у них остаются наблюдатели
и внедрённый rng.
"""
import uuid
from collections import namedtuple

from combat_log import CombatEvent
from entities import Enemy
from factory import EnemyFactory

from battle_map_model import BattleMap


HISTORY_LIMIT = 100

_Step = namedtuple('_Step', ('label', 'before', 'after'))


class RestoreResult:
    """Что поменялось при наложении снимка. Интерфейсу этого хватает, чтобы
    не пересобирать списки и журнал, если изменились только хиты или клетка."""

    def __init__(self, roster_changed, events_changed, selected, selection=None):
        self.roster_changed = roster_changed
        self.events_changed = events_changed
        self.selected = selected
        self.selection = list(selection if selection is not None
                              else ([selected] if selected is not None else []))


class BattleHistory:
    """Стек снимков. Новый шаг после отмены стирает хвост повтора."""

    def __init__(self, limit=HISTORY_LIMIT):
        if int(limit) < 1:
            raise ValueError('лимит истории должен быть не меньше 1')
        self.limit = int(limit)
        self._undo = []
        self._redo = []

    def commit(self, label, before, after):
        """Кладёт шаг, если снимки различаются. Возвращает False для пустой правки."""
        if before == after:
            return False
        self._undo.append(_Step(str(label), before, after))
        extra = len(self._undo) - self.limit
        if extra > 0:
            del self._undo[:extra]
        self._redo.clear()
        return True

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo_label(self):
        return self._undo[-1].label if self._undo else None

    def redo_label(self):
        return self._redo[-1].label if self._redo else None

    def undo(self):
        if not self._undo:
            raise IndexError('нечего отменять')
        step = self._undo.pop()
        self._redo.append(step)
        return step.before

    def redo(self):
        if not self._redo:
            raise IndexError('нечего повторять')
        step = self._redo.pop()
        self._undo.append(step)
        return step.after

    def clear(self):
        self._undo.clear()
        self._redo.clear()

    def __len__(self):
        return len(self._undo)


def ensure_uid(enemy):
    uid = getattr(enemy, 'uid', None)
    if not uid:
        uid = uuid.uuid4().hex
        enemy.uid = uid
    return uid


def _num(value):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 2 ** 53:
            return int(value)
        return value
    return value


def _plain(value):
    """Глубокая копия из списков, словарей и чисел. Снимок не делит объекты с боем."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return [_plain(item) for item in sorted(value, key=_sort_key)]
    if isinstance(value, (str, bool)) or value is None:
        return value
    if isinstance(value, (int, float)):
        return _num(value)
    raise TypeError(f'снимок не умеет хранить {type(value).__name__}')


def _sort_key(value):
    return (str(type(value).__name__), str(value))


def _pair(pos):
    if pos is None:
        return None
    return [_num(pos[0]), _num(pos[1])]


def _setup_rows(source):
    cards = getattr(source, 'cards', None)
    if cards is not None:
        rows = []
        for card in cards:
            rows.append({
                'name': card['name'].text(),
                'type': card['type'],
                'strategy': card['strat'].currentText(),
                'count': int(card['count'].value()),
            })
        return rows
    return _plain(getattr(source, 'setup', None) or [])


def _attack_sig(enemy):
    rows = []
    for attack in enemy.attacks:
        rows.append((
            attack.name, attack.attack_bonus, attack.damage_dice_count,
            attack.damage_dice_type, attack.damage_modifier, attack.damage_type,
            attack.range_ft, bool(attack.magical),
            tuple(tuple(sorted(part.items())) for part in (attack.extra_damage or [])),
            tuple(tuple(sorted(part.items())) for part in (attack.riders or [])),
        ))
    return tuple(rows)


def _cond_sig(enemy):
    rows = []
    for item in enemy.conditions or []:
        if isinstance(item, dict):
            rows.append(tuple(sorted((str(key), _plain(value)) for key, value in item.items())))
        else:
            rows.append((str(item),))
    return tuple(rows)


def _text_bag(value):
    if isinstance(value, dict):
        return tuple(sorted((str(key), str(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_text_bag(item) if isinstance(item, (dict, list, tuple)) else item
                     for item in value)
    return value


def _enemy_sig(enemy, pos):
    """Поля, которые правят бой и карточка. Совпадение — прежняя запись ещё верна."""
    return (
        enemy.name, enemy.max_hp, enemy.hp, enemy.ac, enemy.side, bool(enemy.alive),
        _num(enemy.regen), _num(enemy.speed), _pair(pos),
        _num(getattr(enemy, 'moved_ft', 0) or 0),
        enemy.strategy.__class__.__name__,
        tuple(sorted(int(item) for item in (enemy.ignore_sides or ()))),
        _attack_sig(enemy), _cond_sig(enemy),
        _text_bag(enemy.ability_scores), _text_bag(enemy.ability_mods),
        _text_bag(enemy.saves), _text_bag(enemy.skills), _text_bag(enemy.senses),
        _text_bag(enemy.vulnerabilities), _text_bag(enemy.resistances),
        _text_bag(enemy.immunities), _text_bag(enemy.condition_immunities),
        _text_bag(enemy.languages), enemy.cr, enemy.prof_bonus, enemy.size, enemy.type,
        _text_bag(enemy.traits), _text_bag(enemy.multiattack),
        enemy.legendary_remaining, enemy.legendary_resistance_remaining,
        _text_bag(enemy.recharge_state), _text_bag(enemy.save_immunities),
        int(enemy.lair_index or 0), bool(enemy.lair_warned),
        int(getattr(enemy, 'initiative_bonus', 0) or 0),
        id(enemy.legendary_actions), id(enemy.legendary_resistance),
        id(enemy.lair_actions), id(enemy.special_actions),
        id(enemy.bonus_actions), id(enemy.reactions),
    )


def _enemy_record(enemy, battle_map):
    if battle_map is not None and battle_map.get_pos(enemy) is not None:
        pos = battle_map.get_pos(enemy)
    else:
        pos = getattr(enemy, 'pos', None)
    sig = _enemy_sig(enemy, pos)
    cached = getattr(enemy, '_snap_cache', None)
    if cached is not None and cached[0] == sig:
        return cached[1]
    record = _plain(enemy.to_dict())
    record['uid'] = ensure_uid(enemy)
    record['moved_ft'] = _num(getattr(enemy, 'moved_ft', 0) or 0)
    record['ignore_sides'] = sorted(int(item) for item in (record.get('ignore_sides') or []))
    record['pos'] = _pair(pos)
    enemy._snap_cache = (sig, record)
    return record


# Повторный снимок журнала не сериализует старые строки заново.
_EVENT_CACHE = {}


def _event_record(event, id_to_uid):
    actor = id_to_uid.get(getattr(event, 'actor_id', None))
    target = id_to_uid.get(getattr(event, 'target_id', None))
    area = tuple(id_to_uid.get(item, item) for item in (getattr(event, 'area_ids', None) or []))
    key = (id(event), getattr(event, 'kind', None), getattr(event, 'round', None),
           getattr(event, 'text', None), actor, target, area)
    cached = _EVENT_CACHE.get(key[0])
    if cached is not None and cached[0] == key:
        return cached[1]
    data = event.to_dict()
    for field, value in (('actor_id', actor), ('target_id', target)):
        if value is not None and getattr(event, field, None) in id_to_uid:
            data[field] = value
    if data.get('area_ids'):
        data['area_ids'] = list(area)
    for roll in data.get('rolls') or []:
        if isinstance(roll, dict) and roll.get('actor_id') in id_to_uid:
            roll['actor_id'] = id_to_uid[roll['actor_id']]
    _EVENT_CACHE[key[0]] = (key, data)
    if len(_EVENT_CACHE) > 20000:
        _EVENT_CACHE.clear()
        _EVENT_CACHE[key[0]] = (key, data)
    return data


def capture_battle(source):
    """Снимок боя. Поля source — те же, что у окна: sides, battle_map, engine, …"""
    sides = getattr(source, 'sides', None) or []
    battle_map = getattr(source, 'battle_map', None)
    records = []
    id_to_uid = {}
    for side in sides:
        row = []
        for enemy in side:
            record = _enemy_record(enemy, battle_map)
            id_to_uid[id(enemy)] = record['uid']
            row.append(record)
        records.append(row)

    if battle_map is None:
        map_state = None
    else:
        positions = {}
        for side in sides:
            for enemy in side:
                pos = battle_map.get_pos(enemy)
                if pos is not None:
                    positions[enemy.uid] = _pair(pos)
        map_state = {
            'width': int(battle_map.width),
            'height': int(battle_map.height),
            'positions': positions,
        }
        terrain = battle_map.terrain_records() if hasattr(battle_map, 'terrain_records') else []
        if terrain:
            map_state['terrain'] = terrain

    ignore = {}
    for key, value in (getattr(source, 'ignore_sides', None) or {}).items():
        ignore[str(int(key))] = sorted(int(item) for item in value)

    engine = getattr(source, 'engine', None)
    engine_log = []
    if engine is not None:
        engine_log = _plain(getattr(engine, '_round_log', []) or [])

    selected = getattr(source, 'selected', None)
    selected_uid = None
    if selected is not None:
        selected_uid = ensure_uid(selected)
    group = getattr(source, 'selection', None)
    if group is None:
        selected_uids = [selected_uid] if selected_uid else []
    else:
        selected_uids = [ensure_uid(enemy) for enemy in group if enemy is not None]

    return {
        'sides': records,
        'side_names': [str(name) for name in (getattr(source, 'side_names', None) or [])],
        'ignore_sides': ignore,
        'alliance_settings': _plain(getattr(source, 'alliance_settings', None) or []),
        'map': map_state,
        'round_no': int(getattr(source, 'round_no', 0) or 0),
        'events': [_event_record(event, id_to_uid)
                   for event in (getattr(source, 'battle_events', None) or [])],
        'engine_log': engine_log,
        'setup': _setup_rows(source),
        'custom_types': _plain(dict(EnemyFactory.CUSTOM_TYPES)),
        'selected_uid': selected_uid,
        'selected_uids': selected_uids,
    }


def _write_enemy(enemy, data):
    """Накладывает поля, не трогая наблюдателей и rng."""
    fresh = Enemy.from_dict(_plain(data))
    observers = list(enemy._observers)
    rng = enemy._rng
    enemy.__dict__.clear()
    enemy.__dict__.update(fresh.__dict__)
    enemy._observers = observers
    enemy._rng = rng
    enemy.uid = data.get('uid')
    enemy.moved_ft = _num(data.get('moved_ft') or 0)
    return enemy


def _spawn_enemy(data):
    enemy = Enemy.from_dict(_plain(data))
    enemy.uid = data.get('uid')
    enemy.moved_ft = _num(data.get('moved_ft') or 0)
    return enemy


def _remap_event(data, uid_to_id):
    payload = _plain(data)
    for key in ('actor_id', 'target_id'):
        if payload.get(key) in uid_to_id:
            payload[key] = uid_to_id[payload[key]]
    if payload.get('area_ids'):
        payload['area_ids'] = [uid_to_id.get(item, item) for item in payload['area_ids']]
    for roll in payload.get('rolls') or []:
        if isinstance(roll, dict) and roll.get('actor_id') in uid_to_id:
            roll['actor_id'] = uid_to_id[roll['actor_id']]
    return CombatEvent.from_dict(payload)


def _live_events(events, id_to_uid):
    return [_event_record(event, id_to_uid) for event in events]


def _roster_key(source):
    names = tuple(str(name) for name in (getattr(source, 'side_names', None) or []))
    rows = []
    for side in getattr(source, 'sides', None) or []:
        rows.append(tuple(ensure_uid(enemy) for enemy in side))
    return names, tuple(rows)


def apply_snapshot(snapshot, target):
    """Накладывает снимок на target. Снимок не меняется."""
    roster_before = _roster_key(target)
    pool = {}
    for side in getattr(target, 'sides', None) or []:
        for enemy in side:
            pool[ensure_uid(enemy)] = enemy

    new_sides = []
    for row in snapshot.get('sides') or []:
        side = []
        for data in row:
            enemy = pool.get(data.get('uid'))
            if enemy is None:
                enemy = _spawn_enemy(data)
            else:
                _write_enemy(enemy, data)
            side.append(enemy)
        new_sides.append(side)
    target.sides = new_sides
    target.side_names = [str(name) for name in (snapshot.get('side_names') or [])]
    target.ignore_sides = {
        int(key): set(int(item) for item in value)
        for key, value in (snapshot.get('ignore_sides') or {}).items()
    }
    target.alliance_settings = _plain(snapshot.get('alliance_settings') or [])
    target.round_no = int(snapshot.get('round_no') or 0)
    target.setup = _plain(snapshot.get('setup') or [])

    box = EnemyFactory.CUSTOM_TYPES
    box.clear()
    for name, data in (snapshot.get('custom_types') or {}).items():
        box[name] = _plain(data)

    map_state = snapshot.get('map')
    if map_state is None:
        target.battle_map = None
    else:
        battle_map = BattleMap(int(map_state['width']), int(map_state['height']))
        if hasattr(battle_map, 'load_terrain'):
            battle_map.load_terrain(map_state.get('terrain'))
        positions = map_state.get('positions') or {}
        for side in new_sides:
            for enemy in side:
                pos = positions.get(enemy.uid)
                if pos is not None:
                    battle_map.place(enemy, pos[0], pos[1])
                else:
                    enemy.pos = None
        target.battle_map = battle_map

    uid_to_id = {}
    id_to_uid = {}
    for side in new_sides:
        for enemy in side:
            uid_to_id[enemy.uid] = id(enemy)
            id_to_uid[id(enemy)] = enemy.uid

    wanted_events = snapshot.get('events') or []
    roster_changed = _roster_key(target) != roster_before
    same_events = (not roster_changed
                   and _live_events(getattr(target, 'battle_events', None) or [], id_to_uid)
                   == wanted_events)
    if same_events:
        events_changed = False
    else:
        target.battle_events = [_remap_event(item, uid_to_id) for item in wanted_events]
        events_changed = True

    engine = getattr(target, 'engine', None)
    if engine is not None:
        engine._round_log = _plain(snapshot.get('engine_log') or [])

    selected = None
    selected_uid = snapshot.get('selected_uid')
    if selected_uid:
        for side in new_sides:
            for enemy in side:
                if enemy.uid == selected_uid:
                    selected = enemy
                    break
            if selected is not None:
                break
    target.selected = selected
    by_uid = {enemy.uid: enemy for side in new_sides for enemy in side}
    wanted = snapshot.get('selected_uids')
    if wanted is None:
        wanted = [selected_uid] if selected_uid else []
    group = [by_uid[uid] for uid in wanted if uid in by_uid]
    if hasattr(target, 'selection'):
        target.selection = group
    if selected is None and group:
        selected = group[-1]
        target.selected = selected
    return RestoreResult(roster_changed, events_changed, selected, group)
