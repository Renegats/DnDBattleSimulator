"""Чистый слой импорта бестиария (сеть + разбор), без tkinter и без Qt.

Скорость: парсер lxml при наличии (в разы быстрее html.parser на больших
страницах dnd.su), кэш страниц и разобранных статблоков, один DOM на статблок
(extract_gallery переиспользует soup, а не парсит HTML заново).

Разбор идёт по карточке ``ul.params``, а не по всему тексту страницы: комментарии
и меню больше не подмешиваются в атаки. Ошибки попадают в ``errors``,
недобор — в ``warnings``. Заглушка «Атака +0, 1d6» не подставляется.
"""
import hashlib
import re
import time
from collections import OrderedDict
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from statblock_parser import (parse_characteristics, extract_statblock_text,
                              extract_battle_text, extract_card, clean_text,
                              ABILITY_ORDER, ABILITY_LABEL)

try:                                   # lxml необязателен: без него работаем медленнее
    import lxml  # noqa: F401
    PARSER = 'lxml'
except Exception:
    PARSER = 'html.parser'

MONSTER_URL_RE = re.compile(r'/(?:multiverse/)?bestiary/\d+[-_][\w\-]+/?$')
# «Рукопашная атака оружием», «Рукопашная или дальнобойная…», «атака заклинанием»,
# «Бросок атаки» / «Бросок рукопашной атаки» (MM24 на next.dnd.su).
ATTACK_LEAD = re.compile(
    r'^(?P<name>.+?)\s*\.\s*'
    r'(?P<head>Бросок(?:\s+(?P<bk>рукопашн\w+|дальнобойн\w+))?\s+атаки|'
    r'(?P<k1>Рукопашная|Дальнобойная)'
    r'(?:\s+или\s+(?P<k2>дальнобойная|рукопашная))?\s+атака\s+'
    r'(?P<mode>оружием|заклинанием))'
    r'\s*:?\s*(?P<bonus>[+-]?\d+)',
    re.IGNORECASE | re.DOTALL)
DICE_RE = re.compile(
    r'\(\s*(?P<count>\d+)\s*[кkдdKК]\s*(?P<die>\d+)\s*'
    r'(?:(?P<sign>[+\-])\s*(?P<mod>\d+))?\s*\)',
    re.IGNORECASE)
ACTION_SPLIT = re.compile(
    r'(?<=\.\s)(?=(?:Мультиатака|[А-ЯЁA-Z][^.]{1,60}?)\s*\.\s*'
    r'(?:Бросок\s|Рукопашн|Дальнобойн))',
    re.IGNORECASE)
MULTI_ITEM = re.compile(
    r'(?P<num>\d+|одн\w+|дв[аеухмяи]+|тр[еиё]\w*|четыр\w+|пят\w+|шест\w+|'
    r'сем\w+|вос[еь]м\w+|девят\w+|десят\w+)\s+'
    r'(?:атак\w*\s+)?'
    r'(?P<part>[А-ЯЁа-яёA-Za-z][\w\-]*'
    r'(?:\s+(?!и\b|или\b|а\b|затем\b|он\b|она\b|это\b)[А-ЯЁа-яёA-Za-z][\w\-]*)?)',
    re.IGNORECASE)
MAGIC_INLINE_RE = re.compile(r'(?<!не)магическ', re.IGNORECASE)
MAGIC_TRAIT_RE = re.compile(r'(магическ\w*\s+оружи|magic\s+weapons)', re.IGNORECASE)
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_BACKOFF = (0.4, 0.8)
CACHE_DIR = Path(__file__).parent / '.bestiary_cache'
EXT_RE_IMG = re.compile(r'\.(jpe?g|png|webp|gif)(?:\?|#|$)', re.IGNORECASE)
DAMAGE_TYPE_MAP = [
    ('рубящ', 'рубящий'), ('колющ', 'колющий'), ('пронзающ', 'пронзающий'),
    ('дробящ', 'дробящий'), ('огнен', 'огненный'), ('огн', 'огонь'),
    ('кислот', 'кислотный'), ('холод', 'холод'), ('электрич', 'электрический'),
    ('молни', 'молнии'), ('психическ', 'психическая энергия'), ('психич', 'психический'),
    ('силов', 'силовое поле'), ('излуч', 'излучение'), ('некротич', 'некротический'),
    ('яд', 'яд'), ('гром', 'гром'),
]
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'}
NUM_WORDS = {
    'один': 1, 'одна': 1, 'одну': 1, 'одной': 1, 'одним': 1, 'одно': 1,
    'два': 2, 'две': 2, 'двух': 2, 'двум': 2, 'двумя': 2,
    'три': 3, 'трёх': 3, 'трех': 3, 'трём': 3, 'трем': 3, 'тремя': 3,
    'четыре': 4, 'четырёх': 4, 'четырех': 4, 'четырём': 4, 'четырем': 4,
    'пять': 5, 'пяти': 5, 'шесть': 6, 'шести': 6, 'семь': 7, 'семи': 7,
    'восемь': 8, 'восьми': 8, 'девять': 9, 'девяти': 9, 'десять': 10, 'десяти': 10,
}
SUFFIXES = sorted([
    'иями', 'ями', 'ами', 'ыми', 'ими', 'ого', 'ому', 'ых', 'их',
    'ая', 'яя', 'ое', 'ее', 'ые', 'ие', 'ый', 'ий', 'ой', 'ою', 'ею',
    'ам', 'ям', 'ом', 'ем', 'ов', 'ев', 'ах', 'ях', 'ия', 'ья',
    'у', 'ю', 'а', 'я', 'и', 'ы', 'е', 'о', 'ь',
], key=len, reverse=True)
_STOP_STEMS = {'атак', 'действ', 'раз'}
_VALID_DICE = {4, 6, 8, 10, 12, 20, 100}

GALLERY_SKIP = ('icon', 'logo', 'sprite', 'favicon', 'avatar', 'dice', 'banner',
                'placeholder', 'noimage', 'no_image', 'empty', 'button', 'flag',
                'emoji', 'smile', 'rating', 'star')
GALLERY_HINT = ('bestiary', 'media', 'image', 'img', 'gallery', 'monster',
                'upload', 'picture', 'photo', 'art')
THUMB_HINT = ('thumb', '_small', '-small', 'mini', 'preview', 'crop',
              '150x', '100x', '200x', '64x', '32x', '50x')

_PAGES = OrderedDict()
_MONSTERS = OrderedDict()
CACHE_CAP = 24


def make_soup(html):
    return BeautifulSoup(html, PARSER)


def _remember(store, key, value):
    store[key] = value
    store.move_to_end(key)
    while len(store) > CACHE_CAP:
        store.popitem(last=False)
    return value


def norm_word(w):
    w = re.sub(r'[^\w\-]+', '', (w or '').lower(), flags=re.UNICODE)
    for suf in SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def _same_stem(left, right):
    if not left or not right:
        return False
    if left == right or left.startswith(right) or right.startswith(left):
        return True
    return (len(left) >= 3 and len(right) >= 3 and left[:3] == right[:3]
            and min(len(left), len(right)) <= 6)


def match_attack(part, attacks):
    words = [piece for piece in re.split(r'[\s,]+', part or '') if piece]
    for cand in [part, *words]:
        stem = norm_word(cand)
        if not stem or stem in _STOP_STEMS:
            continue
        for attack in attacks:
            for word in attack['name'].split():
                if _same_stem(stem, norm_word(word)):
                    return attack['name']
    return None


def _count_word(token):
    if not token:
        return None
    if token.isdigit():
        return int(token)
    low = token.lower()
    if low in NUM_WORDS:
        return NUM_WORDS[low]
    return next((value for key, value in NUM_WORDS.items() if low.startswith(key[:3])), None)


def _damage_type(text):
    low = (text or '').lower()
    return next((full for stem, full in DAMAGE_TYPE_MAP if stem in low), '')


def _dice_in(text):
    match = DICE_RE.search(text or '')
    if not match:
        return None
    count = int(match.group('count'))
    die = int(match.group('die'))
    modifier = int((match.group('sign') or '+') + match.group('mod')) if match.group('mod') else 0
    if count < 1 or die not in _VALID_DICE:
        return None
    return count, die, modifier


def _damage_parts(clause, warnings):
    """Первая часть — основной урон, остальные «плюс …» — дополнительный.

    Кусок с «если» (урон только при преимуществе и т.п.) не берём в бой:
    движок преимущество не считает, и предупреждение остаётся в карточке.
    """
    pieces = [piece.strip(' ,;.') for piece in re.split(r'\s*,?\s*плюс\s+', clause or '', flags=re.I)
              if piece.strip(' ,;.')]
    parsed = []
    for index, piece in enumerate(pieces):
        if index and re.search(r'\bесли\b', piece, re.I):
            warnings.append('условный дополнительный урон не импортирован')
            continue
        dice = _dice_in(piece)
        if not dice:
            continue
        count, die, modifier = dice
        parsed.append({'dice_count': count, 'dice_type': f'd{die}', 'modifier': modifier,
                       'damage_type': _damage_type(piece)})
    return parsed


def explode_blocks(paragraph):
    text = clean_text(paragraph)
    if not text:
        return []
    ordered = sorted({0, *(match.start() for match in ACTION_SPLIT.finditer(text))})
    blocks = []
    for index, start in enumerate(ordered):
        end = ordered[index + 1] if index + 1 < len(ordered) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            blocks.append(chunk)
    return blocks


def _range_ft(rest, head, bk, k1, k2):
    reach = re.search(r'досягаемост\w*\s*(\d+)', rest, re.I)
    distance = re.search(r'дистанци\w*\s*(\d+)', rest, re.I)
    reach_ft = int(reach.group(1)) if reach else None
    dist_ft = int(distance.group(1)) if distance else None
    ranged = False
    if bk and bk.lower().startswith('дально'):
        ranged = True
    if k1 and k1.lower().startswith('дально'):
        ranged = True
    if k2:
        ranged = True
    if (head or '').lower().startswith('бросок') and not bk and dist_ft:
        ranged = True
    if ranged:
        return dist_ft or reach_ft or 5
    return reach_ft or 5


def parse_attack_block(text, warnings):
    """Один абзац атаки -> dict или None, если это не бросок атаки."""
    cleaned = clean_text(text)
    match = ATTACK_LEAD.match(cleaned)
    if not match:
        return None
    rest = cleaned[match.end():]
    hit = re.split(r'попадание\s*:?', rest, maxsplit=1, flags=re.I)
    clause = hit[1] if len(hit) > 1 else rest
    parts = _damage_parts(clause, warnings)
    if not parts:
        warnings.append(f"атака «{clean_text(match.group('name'))}»: нет костей урона")
        return None
    primary, *extras = parts
    mode = (match.group('mode') or '').lower()
    magical = mode == 'заклинанием' or bool(MAGIC_INLINE_RE.search(rest))
    attack = {
        'name': clean_text(match.group('name')).strip(' .'),
        'attack_bonus': int(match.group('bonus')),
        'damage_dice_count': primary['dice_count'],
        'damage_dice_type': primary['dice_type'],
        'damage_modifier': primary['modifier'],
        'damage_type': primary['damage_type'],
        'range_ft': _range_ft(rest, match.group('head'), match.group('bk'),
                              match.group('k1'), match.group('k2')),
        'magical': magical,
    }
    if extras:
        attack['extra_damage'] = extras
    from effects import parse_on_hit
    riders, rider_warnings = parse_on_hit(cleaned)
    if riders:
        attack['riders'] = riders
    warnings.extend(rider_warnings)
    return attack


def parse_multiattack(text, attacks, warnings=None):
    """Список ударов мультиатаки или None. Частичный разбор пишет предупреждение."""
    warnings = warnings if warnings is not None else []
    match = re.search(r'(?:Мультиатака|Multiattack)\s*\.?\s*', text or '', re.I)
    if not match:
        return None
    body = text[match.end():]
    replaced = re.split(
        r'(?:он\s+может\s+заменить|может\s+заменить|вместо\s+одной|вместо\s+этого)',
        body, maxsplit=1, flags=re.I)
    if len(replaced) > 1:
        warnings.append('условные замены атак в мультиатаке не импортируются')
    body = replaced[0]
    strikes, seen = [], set()
    unmatched = False
    for item in MULTI_ITEM.finditer(body):
        count = _count_word(item.group('num'))
        if not count:
            continue
        part = item.group('part')
        if norm_word(part.split()[0]) in _STOP_STEMS:
            continue
        name = match_attack(part, attacks)
        if not name:
            unmatched = True
            continue
        key = (name, count)
        if key in seen:
            continue
        seen.add(key)
        strikes.append({'attack': name, 'count': count})
    if unmatched:
        warnings.append('мультиатака распознана частично')
    if not strikes:
        warnings.append('мультиатака не распознана')
        return None
    return strikes


def _named_action(text):
    match = re.match(r'^([А-ЯЁA-Z][^.]{1,80}?)\s*\.\s+(.+)$', clean_text(text), re.S)
    if not match:
        return None
    return {'name': clean_text(match.group(1)), 'desc': clean_text(match.group(2))}


def _attach_effect(action, warnings):
    """Кладёт разобранный спасбросок в действие. Неразобранный текст остаётся как есть."""
    if not action:
        return None
    from effects import parse_special_effect
    effect, warning = parse_special_effect(action.get('name'), action.get('desc'))
    if effect:
        action['effect'] = effect
    elif warning:
        warnings.append(warning)
    return action


def parse_action_blocks(paragraphs, warnings):
    """Абзацы раздела «Действия» -> атаки, мультиатака, особые действия."""
    attacks, specials, deferred = [], [], []
    seen = set()
    for paragraph in paragraphs or []:
        for block in explode_blocks(paragraph):
            if re.match(r'^(?:Мультиатака|Multiattack)\b', block, re.I):
                deferred.append(block)
                continue
            attack = parse_attack_block(block, warnings)
            if attack:
                key = (attack['name'], attack['attack_bonus'], attack['damage_dice_count'],
                       attack['damage_dice_type'])
                if key not in seen:
                    seen.add(key)
                    attacks.append(attack)
                continue
            named = _named_action(block)
            if named and not named['name'].lower().startswith('попадание'):
                specials.append(_attach_effect(named, warnings))
    multi = None
    if deferred:
        multi = parse_multiattack('\n'.join(deferred), attacks, warnings)
    return attacks, multi, specials


def parse_attacks(text, warnings=None):
    """Атаки из плоского текста. Пустой список, если ничего не узнали — без заглушки."""
    warnings = warnings if warnings is not None else []
    paragraphs = [piece for piece in re.split(r'\n+', text or '') if piece.strip()]
    attacks, _multi, _specials = parse_action_blocks(paragraphs or [text or ''], warnings)
    return attacks


def _legendary_option(text, attacks):
    named = _named_action(text)
    if not named:
        return None
    if re.search(r'может совершить|использован\w+\s+легендарн|есть\s+\d+\s+использован',
                 named['name'], re.I):
        return None
    cost_match = re.search(r'стоит\s+(\d+)\s+действ', text, re.I)
    cost = int(cost_match.group(1)) if cost_match else 1
    name = re.sub(r'\s*\([^)]*\)\s*$', '', named['name']).strip()
    desc = named['desc']
    use = re.search(
        r'(?:использует|совершает(?:\s+(?:одну|две|три|\d+))?(?:\s+атак\w*)?)\s+(.+?)(?:\.|$)',
        desc, re.I)
    attack_name = match_attack(use.group(1), attacks) if use else None
    if attack_name is None:
        attack_name = match_attack(name, attacks)
    usable = bool(attack_name) and not re.search(r'спасброс|перемещ|заклинани', desc, re.I)
    count_match = re.search(r'совершает\s+(\d+|одну|две|три)\s+атак', desc, re.I)
    count = _count_word(count_match.group(1)) if count_match else 1
    return {'name': name, 'cost': cost, 'desc': desc, 'attack': attack_name,
            'count': count or 1, 'usable': usable}


def parse_legendary(paragraphs, attacks, warnings):
    per_round = None
    options = []
    for paragraph in paragraphs or []:
        count = re.search(
            r'(\d+)\s+(?:легендарн\w+\s+действ|использован\w+\s+легендарн)',
            paragraph, re.I)
        if count and per_round is None and re.search(
                r'может совершить|есть\s+\d+|использован', paragraph, re.I):
            per_round = int(count.group(1))
            if re.match(r'^(?:Дракон|Лич|Существо|У этого|Монстр)\b', paragraph):
                continue
        option = _legendary_option(paragraph, attacks)
        if option:
            options.append(_attach_effect(option, warnings))
    if not options and per_round is None:
        return None
    if per_round is None:
        per_round = 3
        warnings.append('число легендарных действий не найдено, принято 3')
    return {'per_round': per_round, 'options': options}


def parse_legendary_resistance(traits):
    for trait in traits or []:
        match = re.search(r'легендарное сопротивление\s*\(\s*(\d+)', trait.get('name', ''), re.I)
        if match:
            return {'count': int(match.group(1)), 'name': trait.get('name', ''),
                    'desc': trait.get('desc', '')}
    return None


def _regen_from_traits(traits):
    for trait in traits or []:
        if 'регенер' not in (trait.get('name') or '').lower():
            continue
        match = re.search(r'(\d+)\s+хит', trait.get('desc') or '', re.I)
        if match:
            return int(match.group(1))
    return 0


def format_damage(attack):
    text = (f"{attack['damage_dice_count']}{attack['damage_dice_type']}"
            f"{attack['damage_modifier']:+d}")
    if attack.get('damage_type'):
        text += f" {attack['damage_type']}"
    for extra in attack.get('extra_damage') or []:
        text += f" + {extra['dice_count']}{extra['dice_type']}"
        if extra.get('modifier'):
            text += f"{extra['modifier']:+d}"
        if extra.get('damage_type'):
            text += f" {extra['damage_type']}"
    return text


def extract_gallery(html=None, base_url='https://dnd.su', soup=None, problems=None):
    """Картинки монстра, крупные первыми. soup переиспользуется, если передан."""
    from urllib.parse import urljoin
    big, small, seen = [], [], set()
    try:
        if soup is None:
            soup = make_soup(html or '')

        def push(raw):
            if not raw:
                return
            raw = raw.strip().split()[0]
            if raw.startswith('data:'):
                return
            url = urljoin(base_url, raw)
            if not EXT_RE_IMG.search(url) or url in seen:
                return
            low = url.lower()
            if any(s in low for s in GALLERY_SKIP):
                return
            if not any(h in low for h in GALLERY_HINT):
                return
            seen.add(url)
            (small if any(t in low for t in THUMB_HINT) else big).append(url)

        for a in soup.find_all('a', href=True):
            push(a['href'])
        for tag in soup.find_all('img'):
            for attr in ('data-original', 'data-full', 'data-src', 'data-lazy-src'):
                if tag.get(attr):
                    push(tag[attr])
                    break
            srcset = tag.get('srcset') or ''
            best, best_w = None, -1
            for part in srcset.split(','):
                bits = part.strip().split()
                if not bits:
                    continue
                w = 0
                if len(bits) > 1 and bits[1].endswith('w'):
                    try:
                        w = int(bits[1][:-1])
                    except ValueError:
                        w = 0
                if w > best_w:
                    best, best_w = bits[0], w
            if best:
                push(best)
            push(tag.get('src'))
    except Exception as exc:
        if problems is not None:
            problems.append(f'галерея не разобрана: {exc}')
        return []
    return big + small


def _blank_monster(url):
    return {
        'name': '', 'hp': None, 'ac': None, 'attacks': [], 'regen': 0, 'speed': None,
        'source_url': url, 'multiattack': None, 'warnings': [], 'errors': [],
        'legendary_actions': None, 'legendary_resistance': None, 'lair_actions': None,
        'special_actions': [], 'bonus_actions': [], 'reactions': [],
        'ability_scores': {}, 'ability_mods': {}, 'saves': {}, 'skills': {}, 'senses': {},
        'languages': [], 'vulnerabilities': [], 'resistances': [], 'immunities': [],
        'condition_immunities': [], 'traits': [], 'cr': None, 'prof_bonus': None,
        'size': None, 'type': None,
    }


def _monster_name(soup):
    node = soup.select_one('h2.card-title [data-copy], h2.card-title span, h1')
    name = node.get_text(' ', strip=True) if node else ''
    if not name and soup.title and soup.title.string:
        name = soup.title.string.split('/')[0].strip()
    name = re.sub(r'\s*\[.*?\]', '', name)
    name = re.split(r'\s+(?:MM\d+|FTD|PBSO|MPMM)\b', name)[0]
    name = re.split(r'[—–-]\s*Бестиарий', name)[0]
    name = re.sub(r'\s*\([A-Za-z]{2,6}\)\s*[—–-].*$', '', name)
    return clean_text(name) or 'Без имени'


def _apply_card(card, monster):
    for key in ('hp', 'ac', 'speed', 'cr', 'prof_bonus', 'size', 'type',
                'ability_scores', 'ability_mods', 'saves', 'skills', 'senses',
                'languages', 'vulnerabilities', 'resistances', 'immunities',
                'condition_immunities'):
        if card.get(key) not in (None, {}, []):
            monster[key] = card[key]
    monster['traits'] = list(card.get('traits') or [])
    monster['regen'] = _regen_from_traits(monster['traits'])
    attacks, multi, specials = parse_action_blocks(card.get('actions'), monster['warnings'])
    monster['attacks'] = attacks
    monster['multiattack'] = multi
    monster['special_actions'] = specials
    monster['bonus_actions'] = [item for item in
                                (_attach_effect(_named_action(text), monster['warnings'])
                                 for text in card.get('bonus') or [])
                                if item]
    monster['reactions'] = [item for item in
                            (_attach_effect(_named_action(text), monster['warnings'])
                             for text in card.get('reactions') or [])
                            if item]
    monster['legendary_actions'] = parse_legendary(
        card.get('legendary'), attacks, monster['warnings'])
    monster['legendary_resistance'] = parse_legendary_resistance(monster['traits'])
    if card.get('lair_items') or card.get('lair_intro'):
        monster['lair_actions'] = {
            'intro': card.get('lair_intro') or '',
            'actions': list(card.get('lair_items') or []),
        }


def _parse_loose(soup, monster):
    """Запасной путь, если карточки нет: тот же разбор атак, но по тексту страницы."""
    ref = extract_statblock_text(soup)
    battle = extract_battle_text(soup)
    speed = re.search(r'Скорость\s*(\d+)', ref, re.I)
    if speed:
        monster['speed'] = int(speed.group(1))
    hp = re.search(r'(?:Хиты|Hit\s+Points)[^\d]{0,20}(\d+)', ref, re.I)
    if hp:
        monster['hp'] = int(hp.group(1))
    ac = re.search(r'(?:Класс\s+(?:Доспеха|Защиты)|Armor\s+Class)[^\d]{0,20}(\d+)', ref, re.I)
    if ac:
        monster['ac'] = int(ac.group(1))
    chars = parse_characteristics(soup, ref)
    errors = chars.pop('errors', None)
    if errors:
        monster['errors'].extend(errors)
    monster.update(chars)
    monster['regen'] = _regen_from_traits(monster.get('traits')) or monster.get('regen') or 0
    attacks, multi, specials = parse_action_blocks(
        [piece for piece in re.split(r'\n+', battle) if piece.strip()], monster['warnings'])
    monster['attacks'] = attacks
    monster['multiattack'] = multi
    monster['special_actions'] = specials
    monster['legendary_resistance'] = parse_legendary_resistance(monster.get('traits'))


def _validate(monster):
    warnings = monster.setdefault('warnings', [])
    errors = monster.setdefault('errors', [])
    if monster.get('hp') is None:
        warnings.append('хиты не распознаны')
        monster['hp'] = 10
    if monster.get('ac') is None:
        warnings.append('класс доспеха не распознан')
        monster['ac'] = 10
    if monster.get('speed') is None:
        warnings.append('скорость не распознана')
        monster['speed'] = 30
    scores = monster.get('ability_scores') or {}
    if len(scores) < 6:
        warnings.append('характеристики распознаны не полностью')
    if not monster.get('attacks'):
        warnings.append('атаки не распознаны')
    for attack in monster.get('attacks') or []:
        die = int(str(attack.get('damage_dice_type', 'd0')).split('d')[-1] or 0)
        if attack.get('damage_dice_count', 0) < 1 or die not in _VALID_DICE:
            warnings.append(f"некорректная кость урона: {attack.get('name')}")
        for extra in attack.get('extra_damage') or []:
            extra_die = int(str(extra.get('dice_type', 'd0')).split('d')[-1] or 0)
            if extra.get('dice_count', 0) < 1 or extra_die not in _VALID_DICE:
                warnings.append(f"некорректная кость урона: {attack.get('name')}")
    monster['warnings'] = list(dict.fromkeys(warnings))
    monster['errors'] = list(dict.fromkeys(errors))


def _mark_magic_weapons(monster):
    if any(MAGIC_TRAIT_RE.search(f"{trait.get('name', '')} {trait.get('desc', '')}")
           for trait in (monster.get('traits') or [])):
        for attack in monster['attacks']:
            attack['magical'] = True


def parse_statblock(html, url='https://dnd.su'):
    """Статблок -> словарь. warnings/errors заполнены явно, заглушки атаки нет."""
    monster = _blank_monster(url)
    try:
        soup = make_soup(html or '')
        monster['name'] = _monster_name(soup)
        card = extract_card(soup)
        if card.get('found'):
            _apply_card(card, monster)
        else:
            monster['warnings'].append('карточка статблока не найдена, разбор по тексту страницы')
            _parse_loose(soup, monster)
        _mark_magic_weapons(monster)
        monster['portraits'] = extract_gallery(base_url=url, soup=soup, problems=monster['warnings'])
    except Exception as exc:
        monster['errors'].append(f'разбор прерван: {exc}')
    _validate(monster)
    return monster


def search_monsters(html, query):
    soup = make_soup(html)
    out, seen = [], set()
    q = query.lower()
    for link in soup.find_all('a', href=True):
        href = link['href']
        if not MONSTER_URL_RE.search(href):
            continue
        name = link.get_text(strip=True)
        if not name or q not in name.lower() or href in seen:
            continue
        seen.add(href)
        url = href if href.startswith('http') else f'https://dnd.su{href}'
        out.append({'name': name, 'url': url})
    out.sort(key=lambda e: (not e['name'].lower().startswith(q), e['name'].lower()))
    return out


def fetch(url, params=None, attempts=3):
    """GET с парой повторов на обрыв связи и 429/5xx. Строка поиска — в params."""
    last = None
    tries = max(1, int(attempts))
    for attempt in range(tries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=(6, 20), params=params)
            response.encoding = 'utf-8'
            if response.status_code in RETRY_STATUS and attempt + 1 < tries:
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
                continue
            if response.status_code != 200:
                raise RuntimeError(f'Сайт ответил кодом {response.status_code}')
            return response.text
        except (requests.Timeout, requests.ConnectionError) as exc:
            last = exc
            if attempt + 1 >= tries:
                raise
            time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
    if last:
        raise last
    raise RuntimeError('Сайт не ответил')


def _cache_key(url, params=None):
    if not params:
        return url
    return requests.Request('GET', url, params=params).prepare().url


def _disk_file(key):
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
    return CACHE_DIR / f'{digest}.html'


def fetch_cached(url, params=None):
    """Память, затем небольшой диск-кэш рядом с модулем, затем сеть."""
    key = _cache_key(url, params)
    hit = _PAGES.get(key)
    if hit is not None:
        _PAGES.move_to_end(key)
        return hit
    path = _disk_file(key)
    try:
        if path.is_file():
            return _remember(_PAGES, key, path.read_text(encoding='utf-8'))
    except OSError:
        pass
    text = fetch(url, params=params)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    except OSError:
        pass
    return _remember(_PAGES, key, text)


def fetch_search(query):
    return fetch_cached('https://dnd.su/bestiary/', params={'search': query})


def load_monster(url):
    """Полный цикл для фонового потока: страница (кэш) -> разбор (кэш)."""
    hit = _MONSTERS.get(url)
    if hit is not None:
        _MONSTERS.move_to_end(url)
        return hit
    return _remember(_MONSTERS, url, parse_statblock(fetch_cached(url), url))


def preview_text(m):
    lines = []
    for error in m.get('errors') or []:
        lines.append(f'⛔ {error}')
    for warning in m.get('warnings') or []:
        lines.append(f'⚠ {warning}')
    lines.append(f"👾 {m['name']}")
    head = [m[k] for k in ('size', 'type') if m.get(k)]
    if m.get('cr'):
        head.append(f"CR {m['cr']}")
    if m.get('prof_bonus'):
        head.append(f"Бонус мастерства {m['prof_bonus']}")
    if head:
        lines.append(' · '.join(head))
    lines.append(f"❤️ Хиты: {m['hp']}   🛡️ КД: {m['ac']}   👟 Скорость: {m.get('speed', 30)} фт")
    if m.get('regen'):
        lines.append(f"💚 Регенерация: {m['regen']}")
    sc, md = m.get('ability_scores') or {}, m.get('ability_mods') or {}
    if sc:
        cells = []
        for k in ABILITY_ORDER:
            if k in sc:
                sign = '+' if md.get(k, 0) >= 0 else ''
                cells.append(f"{ABILITY_LABEL[k]} {sc[k]} ({sign}{md.get(k, 0)})")
        lines.append(' · '.join(cells))
    for label, key in (('Спасброски', 'saves'), ('Навыки', 'skills'), ('Чувства', 'senses')):
        d = m.get(key) or {}
        if d:
            lines.append(f"{label}: " + ', '.join(f'{k} {v}'.strip() for k, v in d.items()))
    for label, key in (('Уязвимости', 'vulnerabilities'), ('Сопротивления', 'resistances'),
                       ('Иммунитеты', 'immunities'), ('Иммун. к условиям', 'condition_immunities'),
                       ('Языки', 'languages')):
        lst = m.get(key) or []
        if lst:
            lines.append(f"{label}: " + ', '.join(lst))
    if m.get('multiattack'):
        lines.append('⚔️ Мультиатака: ' + ' + '.join(
            f"{s['attack']}×{s.get('count', 1)}" for s in m['multiattack']))
    lines.append('⚔️ Атаки:' if m.get('attacks') else '⚔️ Атаки: нет')
    for attack in m.get('attacks') or []:
        mark = ' ✦маг.' if attack.get('magical') else ''
        lines.append(f"  • {attack['name']}{mark} ({attack['attack_bonus']:+d}, "
                     f"{format_damage(attack)}) · {attack.get('range_ft', 5)} фт")
    legendary = m.get('legendary_actions') or None
    if legendary:
        lines.append(f"👑 Легендарные действия: {legendary.get('per_round')} за раунд")
        for option in legendary.get('options') or []:
            mark = ' → бой' if option.get('usable') else ''
            lines.append(f"  • {option['name']} (стоит {option.get('cost', 1)}){mark}")
    resist = m.get('legendary_resistance')
    if resist:
        lines.append(f"👑 Легендарное сопротивление: {resist.get('count')}/день")
    lair = m.get('lair_actions') or None
    if lair and lair.get('actions'):
        lines.append(f"🕳 Действия логова: {len(lair['actions'])} (в бою не выполняются)")
    for trait in (m.get('traits') or []):
        lines.append(f"✨ {trait['name']}. {trait['desc']}")
    return '\n'.join(lines)