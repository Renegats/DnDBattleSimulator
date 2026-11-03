"""Разбор СПРАВОЧНЫХ характеристик статблока (этап 1, финальная ревизия).

Спроектирован по LIVE-дампу dnd.su (стр. демогоргона, обе редакции в DOM).
Ключевые решения, выведенные из дампа (не из фантазии о PHB):
(1) поля защиты матчим СТРОГИМ regex с обязательным 'урон*'/'состоян*' после
    слова защиты -> 'Сопротивление магии.' (без 'урон') НЕ поле, а особенность;
    хвосты 'урону'/'к урону' отрезаются целиком;
(2) заголовки разделов ловятся startswith (склеенный get_text() 'ДействияМультиатака');
(3) continuation особенности НЕ теряется (ветка current=='TRAIT');
(4) однословные подписи чистятся сдвигом до границы слова.
Graceful degradation: неизвестная строка -> игнор, неполный источник -> пустые
поля, никогда исключение (дайджест dnd.su: Arcana Unleashed доливается волнами,
'в некоторых монстрах пока не добавлены полные описания').
"""
import re

ABILITY_VARIANTS = {
    'str': ['сил', 'стра', 'strength'],
    'dex': ['лов', 'ловк', 'dexterity'],
    'con': ['тел', 'телос', 'constitution'],
    'int': ['инт', 'интелл', 'intelligence'],
    'wis': ['мдр', 'мудр', 'wisdom'],
    'cha': ['хар', 'харизм', 'charisma'],
}
ABILITY_ORDER = ['str', 'dex', 'con', 'int', 'wis', 'cha']
ABILITY_LABEL = {'str': 'СИЛ', 'dex': 'ЛОВ', 'con': 'ТЕЛ',
                 'int': 'ИНТ', 'wis': 'МДР', 'cha': 'ХАР'}

SIZE_WORDS = (r'(?:Крошечный|Малый|Средний|Крупный|Огромный|Огромное|Гигантский|'
              r'Tiny|Small|Medium|Large|Huge|Gargantuan)')

# Однословные подписи (префикс короче слова -> _cut_prefix сдвигает до границы слова).
LINE_KEYS = [
    ('спасброск',        'saves'),
    ('навык',            'skills'),
    ('чувств',           'senses'),
    ('язык',             'languages'),
    ('опасност',         '__ignore__'),
    ('бонус мастерства', '__ignore__'),
    ('proficiency bonus','__ignore__'),
    ('challenge rating', '__ignore__'),
]

# ПОЛЯ ЗАЩИТЫ: строгий regex, ТРЕБУЕТ 'урон*'/'состоян*' после слова защиты.
# Это отличает 'Сопротивления урону огонь' (поле) от 'Сопротивление магии.' (особенность).
DEFENSE_RE = re.compile(
    r'^(сопротивления?|уязвимости?|иммунитеты?|иммунитет)\s+(?:к\s+)?(урон\w*|состоян\w*)',
    re.IGNORECASE)

SECTION_HEADS = ('действия', 'легендарные действия', 'легендарное действие',
                 'логово', 'местные эффекты', 'культ', 'описание',
                 'действия логова', 'региональные эффекты', 'boss actions',
                 'actions', 'lair actions', 'regional effects', 'description')

TRAIT_STOP = ['существо с точно', 'другой книге', 'другой редакц', '(oota)',
              'господин финик', 'ссылка на аналог', 'вы могли по ошибке',
              'что вам было нужно', 'и блок статистики', 'работа в этой',
              'полные описания', 'присутствует и в']

TRAIT_RE = re.compile(r'^([А-ЯЁA-Z][^.]{2,60}?)\.\s+(.*)$')
BUCKET_FIELDS = ('saves', 'skills', 'senses', 'languages', 'vulnerabilities',
                 'resistances', 'immunities', 'condition_immunities')


def _is_section_heading(line):
    s = line.lower().lstrip('—–-\u00a0 ').strip()
    return any(s.startswith(h) for h in SECTION_HEADS)

def _strip_known_prefix(line):
    """Срезает ведущий заголовок раздела, склеенный get_text() с телом
    ('ДействияСкимитар' -> 'Скимитар...', 'ДействияМультиатака' -> 'Мультиатака...').
    Режет по ТОЧНОМУ префиксу из SECTION_HEADS (без isalpha-сдвига, иначе съест
    имя атаки). Отдельная строка-заголовок -> '' (безвредно для regex-поиска)."""
    s = line.lstrip('—–-\u00a0 \t')
    low = s.lower()
    for h in sorted(SECTION_HEADS, key=len, reverse=True):   # длинные раньше
        if low.startswith(h):
            return s[len(h):].lstrip(' :：\t—–-')
    return line


def _cut_prefix(line, pref_len):
    i, n = pref_len, len(line)
    while i < n and line[i].isalpha():
        i += 1
    return line[i:].strip(' :：\t')


def _match_defense_field(low, line):
    """Поле защиты ИЛИ None. Возвращает (field, rest) только если после слова
    защиты стоит 'урон*'/'состоян*' -> 'Сопротивление магии.' вернёт None."""
    m = DEFENSE_RE.match(low)
    if not m:
        return None
    word, unit = m.group(1).lower(), m.group(2).lower()
    if unit.startswith('состоян'):
        field = 'condition_immunities'
    elif word.startswith('сопротивл'):
        field = 'resistances'
    elif word.startswith('уязвим'):
        field = 'vulnerabilities'
    else:
        field = 'immunities'
    return field, line[m.end():].lstrip(' :：\t')


def extract_statblock_text(soup):
    """Справочный блок + особенности АКТИВНОЙ редакции: от первой size-строки
    до первого заголовка раздела (state-machine сам остановится, но и здесь режем
    для чистоты ref). Graceful: нет size -> 0."""
    lines = soup.get_text().split('\n')
    start = 0
    for i, ln in enumerate(lines):
        if re.search(SIZE_WORDS, ln, re.IGNORECASE):
            start = i
            break
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if _is_section_heading(lines[i]):
            end = i
            break
    return '\n'.join(lines[start:end])


def extract_battle_text(soup):
    """БОЕВОЙ блок активной редакции: от первого заголовка раздела после size-строки
    до границы второй редакции (']CODE' или вторая size-строка). Чинит дубль атак
    (parse_attacks по полному get_text() ловит обе редакции).
    + режет склейку заголовка с первой атакой на ВСЁМ срезе (фикс 'ДействияСкимитар')."""
    lines = soup.get_text().split('\n')
    start1 = 0
    for i, ln in enumerate(lines):
        if re.search(SIZE_WORDS, ln, re.IGNORECASE):
            start1 = i
            break
    h1 = -1
    for i in range(start1 + 1, len(lines)):
        if _is_section_heading(lines[i]):
            h1 = i
            break
    if h1 == -1:
        h1 = start1
    end = len(lines)
    for i in range(h1 + 1, len(lines)):
        ln = lines[i]
        if re.search(r'\]\s*[A-Za-z]{2,6}\s*$', ln) or \
           (i > h1 and re.search(SIZE_WORDS, ln, re.IGNORECASE) and
            any(k in ln.lower() for k in ['исчадие','демон','гигант','нежить','дракон',
                                            'элементаль','зверь','растение','аббераци',
                                            'конструкц','небесн','монстр','fiend','giant',
                                            'undead','dragon','elemental','beast','plant',
                                            'aberration','construct','celestial','monstrosity'])):
            end = i
            break
    # режем склейку заголовка на каждой строке среза (ловит ДействияСкимитар,
    # Легендарные действияВзор, Действия логова… и т.д. на любом монстре)
    sliced = [_strip_known_prefix(ln) for ln in lines[h1:end]]
    return '\n'.join(sliced)


def _parse_size_type(lines):
    if not lines:
        return None, None
    m = re.match(r'\s*(' + SIZE_WORDS + r')\s*[^\w\s]{0,3}\s*(.*)$',
                 lines[0], re.IGNORECASE)
    if not m:
        return None, None
    size = m.group(1).strip()
    parts = [m.group(2).strip()]
    for ln in lines[1:]:
        low = ln.lower()
        if any(k in low for k in ['класс доспеха','хиты','armor class','hit points',
                                  'ac ','спасброск','сил','скорост']):
            break
        if _is_section_heading(ln):
            break
        parts.append(ln.strip())
    typ = re.sub(r'\s+', ' ', ' '.join(p for p in parts if p)).strip(' ,;.')
    return size, (typ or None)


def parse_ability_line(line):
    scores, mods = {}, {}
    for key, variants in ABILITY_VARIANTS.items():
        vs = sorted((re.escape(v) for v in variants), key=len, reverse=True)
        pat = re.compile('(?:' + '|'.join(vs) + r')\s*(-?\d+)\s*\(\s*([+-]?\d+)\s*\)',
                         re.IGNORECASE)
        m = pat.search(line)
        if m:
            scores[key] = int(m.group(1))
            mods[key] = int(m.group(2))
    return scores, mods


def _parse_kv_list(seg):
    seg = (seg or '').strip()
    if not seg:
        return {}, []
    parts = [p.strip() for p in re.split(r'[,;]', seg) if p.strip()]
    pairs, bare = {}, []
    pair_re = re.compile(r'^(.+?)\s+([+-]\d+)$')
    for p in parts:
        m = pair_re.match(p)
        if m:
            pairs[m.group(1).strip()] = m.group(2)
        else:
            bare.append(p)
    return pairs, bare


def _flush_trait(tb):
    return {'name': tb['name'],
            'desc': re.sub(r'\s+', ' ', ' '.join(tb['parts'])).strip()}


def parse_characteristics(soup, text):
    """Точка входа. text = extract_statblock_text(soup). НИКОГДА не бросает."""
    out = {'ability_scores': {}, 'ability_mods': {}, 'saves': {}, 'skills': {},
           'senses': {}, 'vulnerabilities': [], 'resistances': [], 'immunities': [],
           'condition_immunities': [], 'languages': [], 'cr': None,
           'prof_bonus': None, 'size': None, 'type': None, 'traits': []}
    try:
        lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
        if not lines:
            return out

        out['size'], out['type'] = _parse_size_type(lines)
        for ln in lines:
            if re.search(r'СИЛ\s*-?\d+\s*\(', ln, re.IGNORECASE):
                out['ability_scores'], out['ability_mods'] = parse_ability_line(ln)
                break

        joined = '\n'.join(lines)
        cr_m = re.search(r'(?:CR|Опасност[ьи]|Challenge)\D{0,8}?(\d+(?:/\d+)?)', joined, re.I)
        if cr_m:
            out['cr'] = cr_m.group(1)
        pb_m = re.search(r'(?:бонус мастерства|Proficiency Bonus)\D{0,4}?([+-]\d+)', joined, re.I)
        if pb_m:
            out['prof_bonus'] = pb_m.group(1)

        buckets = {f: [] for f in BUCKET_FIELDS}
        current, trait_buf = None, None

        def close_trait():
            nonlocal trait_buf
            if trait_buf:
                out['traits'].append(_flush_trait(trait_buf))
                trait_buf = None

        for ln in lines:
            low = ln.lower()
            if _is_section_heading(ln):                       # 1) конец блока
                close_trait(); break
            df = _match_defense_field(low, ln)                # 2) поле защиты (строго)
            if df:
                close_trait(); current = df[0]
                if df[1]:
                    buckets[current].append(df[1])
                continue
            lk = None                                         # 3) однословный ключ
            for pref, field in LINE_KEYS:
                if low.startswith(pref):
                    lk = (field, _cut_prefix(ln, len(pref))); break
            if lk:
                close_trait(); current = lk[0]
                if current in buckets and lk[1]:
                    buckets[current].append(lk[1])
                continue
            if any(s in low for s in TRAIT_STOP):             # 4) сноска
                close_trait(); current = None; continue
            tm = TRAIT_RE.match(ln)                           # 5) новая особенность
            if tm:
                close_trait(); current = 'TRAIT'
                trait_buf = {'name': tm.group(1).strip(' *'), 'parts': [tm.group(2).strip()]}
                continue
            if current in buckets:                            # 6) continuation поля
                buckets[current].append(ln); continue
            if current == 'TRAIT' and trait_buf:              # 7) continuation особенности
                trait_buf['parts'].append(ln); continue
            current = None                                    # 8) служебное

        close_trait()

        for field in ('saves', 'skills'):
            p, _ = _parse_kv_list(', '.join(buckets[field])); out[field] = p
        p, b = _parse_kv_list(', '.join(buckets['senses']))
        out['senses'] = p if p else {x: '' for x in b}
        for field in ('languages', 'vulnerabilities', 'resistances',
                      'immunities', 'condition_immunities'):
            _, bare = _parse_kv_list(', '.join(buckets[field])); out[field] = bare
    except Exception:
        pass
    return out