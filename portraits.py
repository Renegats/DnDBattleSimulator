"""Портреты существ: галерея dnd.su -> локальный кэш -> карточка отряда.

Чистый модуль без Qt: сеть и файловые операции блокирующие, поэтому вызываются
из QThread (qt_app._portrait_async). Индекс — battle_settings/portraits.json,
файлы — battle_cache/portraits/. Повторный запуск берёт картинку с диска.
"""
import hashlib
import json
import os
import random
import re

import requests

INDEX_FILE = os.path.join('battle_settings', 'portraits.json')
CACHE_DIR = os.path.join('battle_cache', 'portraits')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'}
EXT_RE = re.compile(r'\.(jpe?g|png|webp|gif)(?:\?|#|$)', re.I)
MAGIC = (b'\xff\xd8', b'\x89PNG', b'GIF8', b'RIFF', b'BM')


def _load_index():
    try:
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_index(idx):
    try:
        os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
        with open(INDEX_FILE, 'w', encoding='utf-8') as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def urls_for(type_name):
    return list((_load_index().get(type_name) or {}).get('urls') or [])


def set_urls(type_name, urls):
    """Запоминает галерею типа (дедуп с сохранением порядка)."""
    clean, seen = [], set()
    for u in urls or []:
        if u and u not in seen and EXT_RE.search(u):
            seen.add(u)
            clean.append(u)
    idx = _load_index()
    entry = idx.get(type_name) or {}
    entry['urls'] = clean
    entry['index'] = 0 if clean else None
    idx[type_name] = entry
    _save_index(idx)
    return clean


def pick(type_name, index=None):
    """Выбирает индекс картинки: заданный или случайный (не повторяя текущий)."""
    idx = _load_index()
    entry = idx.get(type_name) or {}
    urls = entry.get('urls') or []
    if not urls:
        return None
    if index is None:
        cur = entry.get('index')
        if len(urls) > 1:
            choices = [i for i in range(len(urls)) if i != cur]
            index = random.choice(choices)
        else:
            index = 0
    index = max(0, min(len(urls) - 1, int(index)))
    entry['index'] = index
    entry['urls'] = urls
    idx[type_name] = entry
    _save_index(idx)
    return index


def _cache_path(url):
    ext = (EXT_RE.search(url).group(1) if EXT_RE.search(url) else 'jpg').lower()
    if ext == 'jpeg':
        ext = 'jpg'
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode('utf-8')).hexdigest() + '.' + ext)


def local_path(type_name):
    """Уже скачанный файл выбранной картинки или None (без сети)."""
    entry = _load_index().get(type_name) or {}
    urls = entry.get('urls') or []
    i = entry.get('index')
    if not urls or i is None or not (0 <= i < len(urls)):
        return None
    p = _cache_path(urls[i])
    return p if os.path.exists(p) and os.path.getsize(p) > 0 else None


def download(url):
    path = _cache_path(url)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f'Картинка отдала код {r.status_code}')
    data = r.content
    if not data or not any(data.startswith(m) for m in MAGIC):
        raise RuntimeError('По ссылке не изображение')
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return path


def ensure_local(type_name, index=None):
    """Блокирующая: выбирает картинку, качает при необходимости, отдаёт путь."""
    urls = urls_for(type_name)
    if not urls:
        return None
    i = pick(type_name, index)
    return {'path': download(urls[i]), 'index': i, 'total': len(urls)}


def find_and_cache(type_name):
    """Ищет монстра по имени на dnd.su и подтягивает его галерею (для пресетов)."""
    urls = urls_for(type_name)
    if not urls:
        import bestiary_core
        results = bestiary_core.search_monsters(bestiary_core.fetch_search(type_name), type_name)
        if not results:
            return None
        page = bestiary_core.fetch(results[0]['url'])
        urls = bestiary_core.extract_gallery(page, results[0]['url'])
        if not urls:
            return None
        set_urls(type_name, urls)
    return ensure_local(type_name, None)

def get_framing(type_name):
    """Сохранённый кадр типа (пустой dict -> возьмётся DEFAULT_FRAMING)."""
    entry = _load_index().get(type_name) or {}
    return dict(entry.get('framing') or {})


def set_framing(type_name, framing):
    idx = _load_index()
    entry = idx.get(type_name) or {}
    entry['framing'] = dict(framing)
    idx[type_name] = entry
    _save_index(idx)