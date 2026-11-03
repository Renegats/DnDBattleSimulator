import tkinter as tk
from tkinter import ttk

ABILITY_ROWS = [('str', 'СИЛ'), ('dex', 'ЛОВ'), ('con', 'ТЕЛ'),
                ('int', 'ИНТ'), ('wis', 'МДР'), ('cha', 'ХАР')]
DICT_FIELDS = [('saves', 'Спасброски'), ('skills', 'Навыки'), ('senses', 'Чувства')]
LIST_FIELDS = [('vulnerabilities', 'Уязвимости к урону'),
               ('resistances', 'Сопротивления урону'),
               ('immunities', 'Иммунитеты к урону'),
               ('condition_immunities', 'Иммунитеты к условиям'),
               ('languages', 'Языки')]
# однострочные справочные
SCALAR_FIELDS = [('cr', 'Опасность (CR)'), ('prof_bonus', 'Бонус мастерства'),
                 ('size', 'Размер'), ('type', 'Тип')]


class CharacteristicsEditor:
    def __init__(self, parent, initial=None, on_change=None, palette=None):
        self.parent = parent
        self.on_change = on_change
        self.palette = palette or {}
        self._entries = {}      # имя поля -> tk.Entry/StringVar (скаляры, ability)
        self._texts = {}        # имя поля -> tk.Text (dict/list/traits)
        self._sections = {}     # ключ секции -> Frame (для сворачивания)
        self._build()
        self.set_data(initial or {})

    # ---------- каркас: две сворачиваемые секции ----------
    def _build(self):
        self._section('stats', '📊 Характеристики', self._build_stats)
        self._section('defense', '🛡 Особенности и защита', self._build_defense)

    def _section(self, key, title, builder):
        wrap = ttk.Frame(self.parent)  # обёртка фиксирует позицию секции в parent
        wrap.pack(fill='x', pady=(4, 0))
        head = ttk.Frame(wrap)
        head.pack(fill='x')
        arrow = ttk.Label(head, text='▸', width=2, cursor='hand2',
                          font=('Segoe UI', 10, 'bold'))
        arrow.pack(side='left')
        lbl = ttk.Label(head, text=title, font=('Segoe UI', 11, 'bold'), cursor='hand2')
        lbl.pack(side='left')
        body = ttk.Frame(wrap)  # НЕ pack-аем здесь: тело живёт внутри wrap
        self._sections[key] = {'body': body, 'arrow': arrow, 'open': False}

        def toggle(_e=None):
            st = self._sections[key]
            if st['open']:
                st['body'].pack_forget()
                st['arrow'].configure(text='▸')
                st['open'] = False
            else:
                st['body'].pack(fill='x', padx=8)  # pack ВНУТРИ wrap -> сразу под head
                st['arrow'].configure(text='▾')
                st['open'] = True

        # bind только на заголовок (не на wrap): клик в пустое место тела не свернёт секцию
        for w in (head, arrow, lbl):
            w.bind('<Button-1>', toggle)
        builder(body)

    # ---------- секция 📊 ----------
    def _build_stats(self, body):
        # ability-сетка 6 строк: СИЛ [score] ( [mod] )
        grid = ttk.Frame(body); grid.pack(fill='x', pady=2)
        for r, (key, label) in enumerate(ABILITY_ROWS):
            ttk.Label(grid, text=label, width=4,
                      font=('Segoe UI', 9, 'bold')).grid(row=r, column=0, sticky='w', padx=(0, 4))
            sv_s = tk.StringVar(); sv_m = tk.StringVar()
            ttk.Entry(grid, textvariable=sv_s, width=5).grid(row=r, column=1, padx=1)
            ttk.Label(grid, text='(').grid(row=r, column=2)
            ttk.Entry(grid, textvariable=sv_m, width=5).grid(row=r, column=3, padx=1)
            ttk.Label(grid, text=')').grid(row=r, column=4)
            self._entries[f'score_{key}'] = sv_s
            self._entries[f'mod_{key}'] = sv_m
            for sv in (sv_s, sv_m):
                sv.trace_add('write', lambda *_: self._emit())
        # dict-поля (saves/skills/senses) - Text 'Ключ Значение' по строке
        for key, label in DICT_FIELDS:
            ttk.Label(body, text=label + ':', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(4, 0))
            self._texts[key] = self._mk_text(body, height=2,
                                             hint='Сил +3, Лов +2  (каждая пара с новой строки или через запятую)')

    # ---------- секция 🛡 ----------
    def _build_defense(self, body):
        # скаляры
        sf = ttk.Frame(body); sf.pack(fill='x', pady=2)
        for c, (key, label) in enumerate(SCALAR_FIELDS):
            col = c % 2
            ttk.Label(sf, text=label + ':', font=('Segoe UI', 9)).grid(
                row=c // 2, column=col * 2, sticky='e', padx=(0, 3))
            sv = tk.StringVar()
            ttk.Entry(sf, textvariable=sv, width=14).grid(row=c // 2, column=col * 2 + 1, sticky='w', padx=(0, 10))
            self._entries[key] = sv
            sv.trace_add('write', lambda *_: self._emit())
        # list-поля - Text через запятую
        for key, label in LIST_FIELDS:
            ttk.Label(body, text=label + ':', font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(4, 0))
            self._texts[key] = self._mk_text(body, height=1,
                                             hint='огонь, холод  (через запятую)')
        # traits - Text 'Имя. Описание' по строке (симметрия с парсером)
        ttk.Label(body, text='Особенности (Имя. Описание, каждая с новой строки):',
                  font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(6, 0))
        self._texts['traits'] = self._mk_text(body, height=4,
                                              hint='Регенерация. Восстанавливает 10 HP в начале хода.')

    # ---------- хелперы Text ----------
    def _mk_text(self, parent, height, hint):
        bg = self.palette.get('field_bg'); fg = self.palette.get('fg')
        kw = {}
        if bg: kw['bg'] = bg
        if fg: kw['fg'] = fg
        t = tk.Text(parent, height=height, wrap='word', font=('Segoe UI', 9), **kw)
        t.pack(fill='x', padx=2)
        t._hint = hint
        t.bind('<FocusIn>', lambda e, w=t: self._hint_clear(w))
        t.bind('<FocusOut>', lambda e, w=t: self._hint_restore(w))
        t.bind('<KeyRelease>', lambda *_: self._emit())
        return t

    def _hint_clear(self, t):
        if t.get('1.0', 'end-1c').strip() == t._hint:
            t.delete('1.0', 'end')
            if self.palette.get('fg'):
                t.configure(fg=self.palette['fg'])

    def _hint_restore(self, t):
        if not t.get('1.0', 'end-1c').strip():
            t.insert('1.0', t._hint)
            if self.palette.get('fg_muted'):
                t.configure(fg=self.palette['fg_muted'])

    # ---------- сериализация dict <-> виджеты ----------
    def set_data(self, data):
        """Заполняет виджеты из dict (вызывается из _load_preset после сборки)."""
        sc = data.get('ability_scores') or {}
        md = data.get('ability_mods') or {}
        for key, _ in ABILITY_ROWS:
            self._entries[f'score_{key}'].set('' if key not in sc else str(sc[key]))
            self._entries[f'mod_{key}'].set('' if key not in md else ('+%d' % md[key] if md[key] >= 0 else str(md[key])))
        for key, _ in SCALAR_FIELDS:
            v = data.get(key)
            self._entries[key].set('' if v is None else str(v))
        for key, _ in DICT_FIELDS:
            d = data.get(key) or {}
            self._set_text(key, ', '.join(f'{k} {v}'.strip() for k, v in d.items()))
        for key, _ in LIST_FIELDS:
            lst = data.get(key) or []
            self._set_text(key, ', '.join(str(x) for x in lst))
        traits = data.get('traits') or []
        self._set_text('traits', '\n'.join(f"{t.get('name','')}. {t.get('desc','')}".strip('. ')
                                           for t in traits))

    def _set_text(self, key, value):
        t = self._texts[key]
        t.delete('1.0', 'end')
        if value:
            t.insert('1.0', value)
            if self.palette.get('fg'):
                t.configure(fg=self.palette['fg'])
        else:
            t.insert('1.0', t._hint)
            if self.palette.get('fg_muted'):
                t.configure(fg=self.palette['fg_muted'])

    def get_data(self):
        """Собирает dict справочных полей из виджетов (для _confirm_custom)."""
        out = {'ability_scores': {}, 'ability_mods': {}, 'saves': {}, 'skills': {},
               'senses': {}, 'vulnerabilities': [], 'resistances': [], 'immunities': [],
               'condition_immunities': [], 'languages': [], 'cr': None,
               'prof_bonus': None, 'size': None, 'type': None, 'traits': []}
        for key, _ in ABILITY_ROWS:
            s = self._parseInt(self._entries[f'score_{key}'].get())
            m = self._parseInt(self._entries[f'mod_{key}'].get())
            if s is not None: out['ability_scores'][key] = s
            if m is not None: out['ability_mods'][key] = m
        for key, _ in SCALAR_FIELDS:
            v = self._entries[key].get().strip()
            out[key] = v if v else None
        for key, _ in DICT_FIELDS:
            out[key] = self._parsePairs(self._getText(key))
        for key, _ in LIST_FIELDS:
            out[key] = self._parseList(self._getText(key))
        out['traits'] = self._parseTraits(self._getText('traits'))
        return out

    # ---------- парсинг ручного ввода (простой, т.к. ввод чистый построчно) ----------
    def _parseInt(self, s):
        s = (s or '').strip()
        if not s: return None
        try: return int(s)
        except ValueError: return None

    def _getText(self, key):
        t = self._texts[key]
        txt = t.get('1.0', 'end-1c').strip()
        return '' if txt == t._hint else txt

    def _parsePairs(self, seg):
        res = {}
        for part in [p.strip() for p in seg.replace('\n', ',').split(',') if p.strip()]:
            # 'Сил +3' или 'Сил: +3'
            import re as _re
            m = _re.match(r'^(.+?)\s*[:\s]\s*([+-]?\d+)$', part)
            if m: res[m.group(1).strip()] = m.group(2)
            elif ' ' in part:
                k, v = part.rsplit(' ', 1)
                res[k.strip()] = v.strip()
        return res

    def _parseList(self, seg):
        return [p.strip() for p in seg.replace('\n', ',').split(',') if p.strip()]

    def _parseTraits(self, seg):
        import re as _re
        out = []
        for line in seg.split('\n'):
            line = line.strip()
            if not line: continue
            m = _re.match(r'^([^.!?:]{1,60}?)\.\s+(.*)$', line)
            if m:
                out.append({'name': m.group(1).strip(' *'), 'desc': m.group(2).strip()})
            else:
                out.append({'name': line, 'desc': ''})
        return out

    def _emit(self):
        if self.on_change:
            try: self.on_change(self.get_data())
            except Exception: pass

    def retint(self, palette):
        """Перекраска tk.Text при смене темы (ttk подхватит стиль сам)."""
        self.palette = palette or {}
        bg, fg, muted = palette.get('field_bg'), palette.get('fg'), palette.get('fg_muted')
        for t in self._texts.values():
            if bg: t.configure(bg=bg)
            cur = t.get('1.0', 'end-1c').strip()
            if cur == t._hint and muted:
                t.configure(fg=muted)
            elif fg:
                t.configure(fg=fg)