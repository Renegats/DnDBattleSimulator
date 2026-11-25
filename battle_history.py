"""История отмены боя. Без Qt и без tkinter.

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

try:
    from battle_map_model import BattleMap
except ImportError:
    from battle_map import BattleMap


HISTORY_LIMIT = 100

_Step = namedtuple('_Step', ('label', 'before', 'after'))


class RestoreResult:
    """Что поменялось при наложении снимка. Интерфейсу этого хватает, чтобы
    не пересобирать списки и журнал, если изменились только хиты или клетка."""

    def __init__(self, roster_changed, events_changed, selected):
        self.roster_changed = roster_changed
        self.events_changed = events_changed
        self.selected = selected


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


def _enemy_record(enemy, battle_map):
    record = _plain(enemy.to_dict())
    record['uid'] = ensure_uid(enemy)
    record['moved_ft'] = _num(getattr(enemy, 'moved_ft', 0) or 0)
    record['ignore_sides'] = sorted(int(item) for item in (record.get('ignore_sides') or []))
    if battle_map is not None and battle_map.get_pos(enemy) is not None:
        record['pos'] = _pair(battle_map.get_pos(enemy))
    else:
        record['pos'] = _pair(record.get('pos'))
    return record


def _event_record(event, id_to_uid):
    data = _plain(event.to_dict())
    for key in ('actor_id', 'target_id'):
        if data.get(key) in id_to_uid:
            data[key] = id_to_uid[data[key]]
    if data.get('area_ids'):
        data['area_ids'] = [id_to_uid.get(item, item) for item in data['area_ids']]
    for roll in data.get('rolls') or []:
        if isinstance(roll, dict) and roll.get('actor_id') in id_to_uid:
            roll['actor_id'] = id_to_uid[roll['actor_id']]
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
    return RestoreResult(roster_changed, events_changed, selected)
