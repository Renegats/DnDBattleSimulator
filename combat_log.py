"""Структурированный журнал боя. Без Qt и без tkinter.

run_round собирает CombatEvent и рисует прежний текстовый лог уже из них
(render_log), чтобы Tk и старые тесты читали те же строки.

Поля hp_before / hp_after / max_hp отделены от факта попадания. conceal_enemy_hp
прячет хиты чужой стороны — заготовка «вида игрока», в интерфейсе её нет.
"""
import json
import os
import re
from dataclasses import asdict, dataclass, field, fields

LOG_VERSION = 1

# Хиты, которые будущий вид игрока скрывает у чужих существ.
GM_ONLY_FIELDS = ('hp_before', 'hp_after', 'max_hp')

_HP_FRACTION = re.compile(r'\s*\(\d+/\d+\)')
_POS_FIELDS = ('from_pos', 'to_pos', 'actor_pos', 'target_pos')


@dataclass
class DamagePart:
    """Урон одного типа: raw — до иммунитета/сопротивления/уязвимости, final — после."""

    damage_type: str
    raw: int
    final: int
    note: str = ''
    extra: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(
            damage_type=data.get('damage_type') or '',
            raw=int(data.get('raw') or 0),
            final=int(data.get('final') or 0),
            note=data.get('note') or '',
            extra=bool(data.get('extra') or False),
        )


@dataclass
class InitiativeRoll:
    name: str
    side: int | None
    actor_id: int | None
    natural: int
    modifier: int
    total: int
    tie_roll: int
    dex: int | None = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data.get('name') or '',
            side=data.get('side'),
            actor_id=data.get('actor_id'),
            natural=int(data.get('natural') or 0),
            modifier=int(data.get('modifier') or 0),
            total=int(data.get('total') or 0),
            tie_roll=int(data.get('tie_roll') or 0),
            dex=data.get('dex'),
        )


@dataclass
class CombatEvent:
    kind: str
    round: int | None = None
    actor: str | None = None
    actor_id: int | None = None
    actor_side: int | None = None
    target: str | None = None
    target_id: int | None = None
    target_side: int | None = None
    action: str | None = None
    natural: int | None = None
    modifier: int | None = None
    attack_total: int | None = None
    ac: int | None = None
    result: str | None = None
    crit: bool = False
    damages: list = field(default_factory=list)
    heal_amount: int | None = None
    hp_before: int | None = None
    hp_after: int | None = None
    max_hp: int | None = None
    from_pos: tuple | None = None
    to_pos: tuple | None = None
    actor_pos: tuple | None = None
    target_pos: tuple | None = None
    reason: str | None = None
    text: str | None = None
    legendary: bool = False
    rolls: list = field(default_factory=list)
    cost: int | None = None
    dc: int | None = None
    save_ability: str | None = None
    condition: str | None = None
    naturals: list = field(default_factory=list)
    advantage: str | None = None
    resistance_used: bool = False
    area_cells: list = field(default_factory=list)
    area_origin: tuple | None = None
    area_ids: list = field(default_factory=list)

    def to_dict(self):
        data = {}
        for item in fields(self):
            data[item.name] = _dump(getattr(self, item.name))
        return data

    @classmethod
    def from_dict(cls, data):
        kwargs = {}
        for item in fields(cls):
            if item.name not in data:
                continue
            value = data[item.name]
            if item.name == 'damages':
                value = [DamagePart.from_dict(part) for part in (value or [])]
            elif item.name == 'rolls':
                value = [InitiativeRoll.from_dict(part) for part in (value or [])]
            elif item.name == 'naturals':
                value = [int(part) for part in (value or []) if part is not None]
            elif item.name == 'area_cells':
                value = [_as_pos(part) for part in (value or []) if _as_pos(part)]
            elif item.name == 'area_ids':
                value = [int(part) for part in (value or []) if part is not None]
            elif item.name in _POS_FIELDS or item.name == 'area_origin':
                value = _as_pos(value)
            kwargs[item.name] = value
        return cls(**kwargs)


class InitiativeEntry:
    """Строка инициативы. Распаковка и [0]..[4] — как у прежнего кортежа из 5 полей."""

    __slots__ = ('total', 'dex', 'tie', 'side_idx', 'enemy', 'natural', 'modifier')

    def __init__(self, total, dex, tie, side_idx, enemy, natural, modifier):
        self.total = total
        self.dex = dex
        self.tie = tie
        self.side_idx = side_idx
        self.enemy = enemy
        self.natural = natural
        self.modifier = modifier

    def __iter__(self):
        yield self.total
        yield self.dex
        yield self.tie
        yield self.side_idx
        yield self.enemy

    def __len__(self):
        return 5

    def __getitem__(self, index):
        return (self.total, self.dex, self.tie, self.side_idx, self.enemy)[index]


class RoundResult:
    """Итог раунда. Распаковка `outcome, text = run_round(...)` сохранена."""

    __slots__ = ('outcome', 'text', 'events')

    def __init__(self, outcome, text, events):
        self.outcome = outcome
        self.text = text
        self.events = list(events)

    def __iter__(self):
        yield self.outcome
        yield self.text

    def __len__(self):
        return 2

    def __getitem__(self, index):
        return (self.outcome, self.text)[index]


def _dump(value):
    if hasattr(value, 'to_dict'):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_dump(part) for part in value]
    if isinstance(value, list):
        return [_dump(part) for part in value]
    return value


def _as_pos(value):
    if not value or not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    return (value[0], value[1])


def format_pos(pos):
    if not pos:
        return '?'

    def one(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if number.is_integer():
            return str(int(number))
        return str(round(number, 2))

    return f'({one(pos[0])}, {one(pos[1])})'


def render_log(events) -> str:
    """Прежний текстовый журнал: строки событий через перевод строки.

    text is None в склейку не входит. Пустая строка (разделитель раунда) входит.
    """
    return '\n'.join(event.text for event in events if event.text is not None)


def detail_lines(event: CombatEvent) -> list:
    """Разбор, которого нет в однострочном тексте: кость, защиты, хиты, причина."""
    lines = []
    if event.kind == 'initiative':
        for roll in event.rolls:
            lines.append(
                f'{roll.name}: d20 {roll.natural} {roll.modifier:+d} = {roll.total}, '
                f'ничья d20 {roll.tie_roll}')
        return lines
    if event.kind == 'attack' and event.natural is not None:
        mod = event.modifier or 0
        label = {
            'crit': 'крит',
            'hit': 'попадание',
            'miss': 'промах',
            'nat1': 'натуральная 1, промах',
        }.get(event.result, event.result or '')
        lines.append(
            f'бросок d20 {event.natural} {mod:+d} = {event.attack_total} '
            f'против КД {event.ac} ({label})')
        if event.advantage == 'advantage' and len(event.naturals) == 2:
            lines.append(
                f'преимущество: кости {event.naturals[0]} и {event.naturals[1]}, '
                f'взята {event.natural}')
        elif event.advantage == 'disadvantage' and len(event.naturals) == 2:
            lines.append(
                f'помеха: кости {event.naturals[0]} и {event.naturals[1]}, '
                f'взята {event.natural}')
        elif event.advantage == 'cancel':
            lines.append('преимущество и помеха взаимно гасятся')
    elif event.kind == 'attack' and event.attack_total is not None:
        lines.append(f'итог атаки {event.attack_total} против КД {event.ac}')
    for part in event.damages:
        prefix = 'доп. ' if part.extra else ''
        note = part.note or ''
        lines.append(
            f'{prefix}{part.damage_type or "урон"}: {part.raw} до защит → {part.final} после{note}')
    if event.kind == 'save':
        ability = event.save_ability or ''
        if event.advantage == 'auto_fail' or event.natural is None:
            lines.append(f'спасбросок {ability}: автоматический провал, Сл {event.dc}')
        elif event.natural is not None:
            mod = event.modifier or 0
            lines.append(
                f'спасбросок {ability}: d20 {event.natural} {mod:+d} = {event.attack_total} '
                f'против Сл {event.dc}')
        if event.resistance_used:
            lines.append('легендарное сопротивление потрачено')
    if event.kind in ('condition', 'recharge', 'lair') and event.condition:
        lines.append(f'состояние: {event.condition}')
    if event.kind == 'heal' and event.heal_amount is not None:
        lines.append(f'лечение +{event.heal_amount}')
    if event.hp_before is not None and event.hp_after is not None and event.kind != 'initiative':
        lines.append(f'HP: {event.hp_before} → {event.hp_after}')
    if event.kind == 'move' and event.from_pos and event.to_pos:
        lines.append(f'с {format_pos(event.from_pos)} на {format_pos(event.to_pos)}')
    if event.legendary and event.kind != 'legendary':
        lines.append('легендарное действие')
    if event.reason and event.reason not in (event.text or ''):
        lines.append(f'причина: {event.reason}')
    if event.area_cells:
        lines.append(f'клеток области: {len(event.area_cells)}')
    return lines


def render_markdown(events) -> str:
    out = ['# Журнал боя', '']
    last_round = object()
    opened = False
    for event in events:
        if event.kind == 'spacer' or not event.text:
            continue
        if event.kind == 'round_start' and event.round != last_round:
            last_round = event.round
            title = f'Раунд {event.round}' if event.round else 'Раунд'
            if opened:
                out.append('')
            out.append(f'## {title}')
            out.append('')
            opened = True
        body = ' '.join(event.text.split())
        out.append(f'- {body}')
        for line in detail_lines(event):
            out.append(f'  - {line}')
    out.append('')
    return '\n'.join(out)


def document_from_events(events) -> dict:
    return {
        'version': LOG_VERSION,
        'gm_only_fields': list(GM_ONLY_FIELDS),
        'events': [event.to_dict() for event in events],
    }


def render_json(events, *, indent=2) -> str:
    return json.dumps(document_from_events(events), ensure_ascii=False, indent=indent)


def events_from_json(payload) -> list:
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(payload, list):
        raw_events = payload
    else:
        raw_events = payload.get('events') or []
    return [CombatEvent.from_dict(item) for item in raw_events]


def dump_log(events, path) -> str:
    """Пишет .json / .md / иначе текст. Возвращает записанную строку."""
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == '.json':
        payload = render_json(events)
    elif ext in ('.md', '.markdown'):
        payload = render_markdown(events)
    else:
        payload = render_log(events)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(payload)
    return payload


def load_events(path) -> list:
    with open(path, 'r', encoding='utf-8') as handle:
        return events_from_json(handle.read())


def _strip_hp_fraction(text: str) -> str:
    return _HP_FRACTION.sub('', text)


def _hp_subject_side(event: CombatEvent):
    """Чьи хиты записаны в событии. Регенерация — хиты действующего."""
    if event.kind == 'heal' and event.action == 'регенерация':
        return event.actor_side
    if event.kind in ('attack', 'death', 'heal'):
        if event.target_side is not None:
            return event.target_side
        return event.actor_side
    return None


def conceal_enemy_hp(event: CombatEvent, viewer_side: int) -> CombatEvent:
    """Копия для будущего вида игрока: точные хиты чужой стороны убраны.

    Попадание, промах, крит, имена и типы урона остаются. В интерфейсе
    переключатель не подключён.
    """
    clone = CombatEvent.from_dict(event.to_dict())
    subject = _hp_subject_side(event)
    if subject is None or subject == viewer_side:
        return clone
    clone.hp_before = None
    clone.hp_after = None
    clone.max_hp = None
    if clone.text:
        clone.text = _strip_hp_fraction(clone.text)
    return clone


def _creature_ids(event: CombatEvent) -> set:
    found = set()
    if event.actor_id is not None:
        found.add(event.actor_id)
    if event.target_id is not None:
        found.add(event.target_id)
    for roll in event.rolls:
        if roll.actor_id is not None:
            found.add(roll.actor_id)
    return found


def _sides(event: CombatEvent) -> set:
    found = set()
    if event.actor_side is not None:
        found.add(event.actor_side)
    if event.target_side is not None:
        found.add(event.target_side)
    for roll in event.rolls:
        if roll.side is not None:
            found.add(roll.side)
    return found


def _kind_ok(event: CombatEvent, kind: str) -> bool:
    if not kind or kind == 'all':
        return True
    if kind == 'hit':
        return event.result in ('hit', 'crit')
    if kind == 'crit':
        return event.result == 'crit'
    if kind == 'miss':
        return event.result in ('miss', 'nat1')
    if kind == 'nat1':
        return event.result == 'nat1'
    if kind == 'death':
        return event.kind == 'death'
    if kind == 'heal':
        return event.kind == 'heal' or event.result == 'heal'
    if kind == 'move':
        return event.kind == 'move'
    if kind == 'legendary':
        return bool(event.legendary) or event.kind == 'legendary'
    if kind == 'initiative':
        return event.kind == 'initiative'
    if kind == 'conditions':
        return event.kind in ('save', 'condition', 'recharge', 'lair')
    return True


def _haystack(event: CombatEvent) -> str:
    chunks = [event.text, event.actor, event.target, event.action, event.reason,
              event.kind, event.result, event.condition, event.save_ability,
              event.advantage]
    for part in event.damages:
        chunks.append(part.damage_type)
        chunks.append(part.note)
    for roll in event.rolls:
        chunks.append(roll.name)
    return ' '.join(str(chunk) for chunk in chunks if chunk)


def event_visible(event, *, side=None, creature_id=None, kind='all', query='') -> bool:
    """Фильтр панели: сторона, существо, тип события, подстрока поиска."""
    if event is None:
        return False
    if side is not None and side not in _sides(event):
        return False
    if creature_id is not None and creature_id not in _creature_ids(event):
        return False
    if not _kind_ok(event, kind):
        return False
    needle = (query or '').strip().casefold()
    if needle and needle not in _haystack(event).casefold():
        return False
    return True


def map_mark(event: CombatEvent, radius_of=None, *, include_moves=False):
    """Один отрезок в координатах клеток или None. Стиль: hit/miss/crit/nat1/heal/move."""

    def radius(creature_id, default=0.45):
        if radius_of is None or creature_id is None:
            return default
        try:
            value = float(radius_of(creature_id))
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    if event.kind == 'move':
        if not include_moves or not event.from_pos or not event.to_pos:
            return None
        reach = radius(event.actor_id)
        return _segment(event.from_pos, event.to_pos, reach, reach, 'move')
    if event.kind == 'attack' and event.actor_pos and event.target_pos:
        style = event.result if event.result in ('hit', 'miss', 'crit', 'nat1') else 'hit'
        return _segment(event.actor_pos, event.target_pos,
                        radius(event.actor_id), radius(event.target_id), style)
    if (event.kind == 'heal' and event.action != 'регенерация'
            and event.actor_pos and event.target_pos):
        return _segment(event.actor_pos, event.target_pos,
                        radius(event.actor_id), radius(event.target_id), 'heal')
    return None


def map_marks(events, radius_of=None, *, include_moves=False) -> list:
    marks = []
    for event in events:
        mark = map_mark(event, radius_of, include_moves=include_moves)
        if mark is not None:
            marks.append(mark)
    return marks


def _segment(start, end, r1, r2, style):
    return {
        'x1': start[0], 'y1': start[1],
        'x2': end[0], 'y2': end[1],
        'r1': r1, 'r2': r2,
        'style': style,
    }
