"""Чистый слой импорта бестиария (сеть + разбор), без tkinter и без Qt.

Скорость: парсер lxml при наличии (в разы быстрее html.parser на больших
страницах dnd.su), кэш страниц и разобранных статблоков, один DOM на статблок
(extract_gallery переиспользует soup, а не парсит HTML заново).
"""
import re
from collections import OrderedDict

import requests
from bs4 import BeautifulSoup

from statblock_parser import (parse_characteristics, extract_statblock_text,
                              extract_battle_text, ABILITY_ORDER, ABILITY_LABEL)

try:                                   # lxml необязателен: без него работаем медленнее
    import lxml  # noqa: F401
    PARSER = 'lxml'
except Exception:
    PARSER = 'html.parser'

MONSTER_URL_RE = re.compile(r'/(?:multiverse/)?bestiary/\d+[-_][\w\-]+/?$')
ATTACK_RE = re.compile(
    r'(?P<name>[А-ЯЁA-Z][^.\n]{2,80}?)\.\s*'
    r'(?P<kind>Рукопашная|Дальнобойная)\s+атака\s+оружием:?\s*'
    r'(?P<bonus>[+-]?\d+)\s+к\s+попаданию', re.IGNORECASE)
DICE_RE = re.compile(r'(\d+)\s*[кkd]\s*(\d+)(?:\s*([+-]\s*\d+))?')
MAGIC_INLINE_RE = re.compile(r'(?<!не)магическ', re.IGNORECASE)
MAGIC_TRAIT_RE = re.compile(r'(магическ\w*\s+оружи|magic\s+weapons)', re.IGNORECASE)
EXT_RE_IMG = re.compile(r'\.(jpe?g|png|webp|gif)(?:\?|#|$)', re.IGNORECASE)
DAMAGE_TYPE_MAP = [
    ('рубящ', 'рубящий'), ('колющ', 'колющий'), ('пронзающ', 'пронзающий'),
    ('дробящ', 'дробящий'), ('огнен', 'огненный'), ('кислот', 'кислотный'),
    ('холод', 'холод'), ('электрич', 'электрический'), ('молни', 'молнии'),
    ('яд', 'яд'), ('психич', 'психический'), ('силов', 'силовое поле'),
    ('излуч', 'излучение'), ('некротич', 'некротический'), ('гром', 'гром'),
]
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'}
NUM_WORDS = {'одна': 1, 'одну': 1, 'одной': 1, 'одним': 1,
             'две': 2, 'двух': 2, 'двум': 2, 'двумя': 2,
             'три': 3, 'трёх': 3, 'трём': 3, 'четыре': 4, 'четырёх': 4, 'четырём': 4,
             'пять': 5, 'пяти': 5, 'шесть': 6, 'шести': 6, 'семь': 7, 'семи': 7,
             'восемь': 8, 'восьми': 8, 'девять': 9, 'девяти': 9, 'десять': 10, 'десяти': 10}
STRIKE_RE = re.compile(
    r'(?:(?P<num>одн[ауюе]|дв[ауюеи]|тр[еиё]|четыр[еиё]?|пяти?|шести?|семи?|восьми?|девяти?|десяти?|\d+)\s+)?'
    r'атак[ауеийок]*\s+(?:оружием\s+|частью\s+|по\s+)?'
    r'(?P<part>[А-ЯЁа-яёA-Za-z][\w\-]*)', re.IGNORECASE)
SUFFIXES = sorted(['иями', 'иям', 'ами', 'ями', 'ам', 'ям', 'ом', 'ем', 'ов', 'ев',
                   'ах', 'ях', 'у', 'ю', 'а', 'я', 'и', 'ы', 'е', 'о'], key=len, reverse=True)

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
    w = w.lower().strip()
    for suf in SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def match_attack(part, attacks):
    np = norm_word(part)
    if not np:
        return None
    for a in attacks:
        words = {norm_word(x) for x in a['name'].split()}
        if np in words or any(np == wd or (len(np) >= 3 and (np in wd or wd in np))
                              for wd in words):
            return a['name']
    return None


def parse_multiattack(text, attacks):
    m = re.search(r'(?:Мультиатака|Multiattack)', text, re.IGNORECASE)
    if not m:
        return None
    window = text[m.end(): m.end() + 320]
    strikes, seen = [], set()
    for sm in STRIKE_RE.finditer(window):
        raw = sm.group('num')
        if raw is None:
            cnt = 1
        elif raw.isdigit():
            cnt = int(raw)
        else:
            cnt = NUM_WORDS.get(raw.lower())
            if cnt is None:
                cnt = next((v for k, v in NUM_WORDS.items()
                            if k.startswith(raw.lower()[:3])), 1)
        name = match_attack(sm.group('part'), attacks)
        if not name or (name, cnt) in seen:
            continue
        seen.add((name, cnt))
        strikes.append({'attack': name, 'count': cnt})
    return strikes or None


def parse_attacks(text):
    attacks, seen = [], set()
    for m in ATTACK_RE.finditer(text):
        name = m.group('name').strip(' _*')
        bonus = int(m.group('bonus'))
        window = text[m.end(): m.end() + 250]
        rm = re.search(r'дистанция\s*(\d+)', window)
        reach = re.search(r'досягаемость\s*(\d+)', window)
        if m.group('kind').lower().startswith('дально') and rm:
            range_ft = int(rm.group(1))
        elif reach:
            range_ft = int(reach.group(1))
        else:
            range_ft = 5
        dm = DICE_RE.search(window)
        if not dm:
            continue
        count, die = int(dm.group(1)), int(dm.group(2))
        mod = int(dm.group(3).replace(' ', '')) if dm.group(3) else 0
        type_window = window[:dm.end() + 60].lower()
        dtype = next((full for stem, full in DAMAGE_TYPE_MAP if stem in type_window), '')
        key = (name, bonus, count, die)
        if key in seen:
            continue
        seen.add(key)
        attacks.append({'name': name, 'attack_bonus': bonus,
                        'damage_dice_count': count, 'damage_dice_type': f'd{die}',
                        'damage_modifier': mod, 'damage_type': dtype,
                        'range_ft': range_ft,
                        'magical': bool(MAGIC_INLINE_RE.search(window))})
    if not attacks:
        attacks.append({'name': 'Атака', 'attack_bonus': 0, 'damage_dice_count': 1,
                        'damage_dice_type': 'd6', 'damage_modifier': 0,
                        'damage_type': '', 'range_ft': 5, 'magical': False})
    return attacks


def extract_gallery(html=None, base_url='https://dnd.su', soup=None):
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
    except Exception:
        return []
    return big + small


def parse_statblock(html, url='https://dnd.su'):
    soup = make_soup(html)
    monster = {'name': '', 'hp': 10, 'ac': 10, 'attacks': [], 'regen': 0, 'speed': 30,
               'source_url': url}
    name = ''
    h1 = soup.find('h1')
    if h1:
        name = h1.get_text(strip=True)
    if not name and soup.title and soup.title.string:
        name = soup.title.string.split('/')[0].strip()
    name = re.sub(r'\s*\[.*?\]', '', name)
    name = re.split(r'[—–-]\s*Бестиарий', name)[0]
    name = re.sub(r'\s*\([A-Za-z]{2,6}\)\s*[—–-].*$', '', name)
    monster['name'] = name.strip() or 'Без имени'

    ref = extract_statblock_text(soup)
    battle = extract_battle_text(soup)
    spd = re.search(r'Скорость\s*(\d+)\s*футов', ref, re.I)
    if spd:
        monster['speed'] = int(spd.group(1))
    hp = re.search(r'(?:Хиты|Hit\s+Points)[^\d]{0,20}(\d+)', ref, re.I)
    if hp:
        monster['hp'] = int(hp.group(1))
    ac = re.search(r'(?:Класс\s+Доспеха|Armor\s+Class)[^\d]{0,20}(\d+)', ref, re.I)
    if ac:
        monster['ac'] = int(ac.group(1))
    regen = re.search(r'(?:восстанавливает|регенерация)[^\d]{0,40}(\d+)\s+хитов', ref, re.I)
    if regen:
        monster['regen'] = int(regen.group(1))
    monster['attacks'] = parse_attacks(battle)
    monster['multiattack'] = parse_multiattack(battle, monster['attacks'])
    monster.update(parse_characteristics(soup, ref))

    if any(MAGIC_TRAIT_RE.search(f"{tr.get('name', '')} {tr.get('desc', '')}")
           for tr in (monster.get('traits') or [])):
        for a in monster['attacks']:
            a['magical'] = True
    monster['portraits'] = extract_gallery(base_url=url, soup=soup)
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


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=(6, 20))
    r.encoding = 'utf-8'
    if r.status_code != 200:
        raise RuntimeError(f'Сайт ответил кодом {r.status_code}')
    return r.text


def fetch_cached(url):
    hit = _PAGES.get(url)
    if hit is not None:
        _PAGES.move_to_end(url)
        return hit
    return _remember(_PAGES, url, fetch(url))


def fetch_search(query):
    return fetch_cached(f'https://dnd.su/bestiary/?search={query}')


def load_monster(url):
    """Полный цикл для фонового потока: страница (кэш) -> разбор (кэш)."""
    hit = _MONSTERS.get(url)
    if hit is not None:
        _MONSTERS.move_to_end(url)
        return hit
    return _remember(_MONSTERS, url, parse_statblock(fetch_cached(url), url))


def preview_text(m):
    lines = [f"👾 {m['name']}"]
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
    lines.append('⚔️ Атаки:')
    for a in m['attacks']:
        mark = ' ✦маг.' if a.get('magical') else ''
        lines.append(f"  • {a['name']}{mark} ({a['attack_bonus']:+d}, "
                     f"{a['damage_dice_count']}{a['damage_dice_type']}"
                     f"{a['damage_modifier']:+d}) {a.get('damage_type', '')} "
                     f"· {a.get('range_ft', 5)} фт")
    for tr in (m.get('traits') or []):
        lines.append(f"✨ {tr['name']}. {tr['desc']}")
    return '\n'.join(lines)