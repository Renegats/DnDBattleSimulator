"""Слой принятия решений существа (v1 + объяснимость).

Две ортогональные оси: temperament (ручной, делегируем) x intellect (INT, авто из
парсера). v1-объём: A (цель + A5-фильтр иммунных), B1/B2/B3 (дальность/защиты/EV),
C1 + hold-половина C2/D1. БЕЗ прогноза F и памяти D4/B5 (v2).

ОБЪЯСНИМОСТЬ (этап СПР-анализ): каждый выход decide фиксирует immutable-снимок
Explanation в self._round_log (НЕ пересчёт - мир к моменту открытия окна изменился).
Снимок хранит имена и числовые мотивы, не ссылки на target/attack (протухнут).
Журнал живёт в ENGINE, а не в BattleLogic: объяснение рождается только в decide,
и тащить его сбор в боевое ядро = смешать слои (battle_logic получает лишь
begin_round()). Единый источник истины о типе урона - dmg_canon здесь.
Graceful под живой источник (дайджест: Arcana Unleashed доливается волнами,
"в некоторых монстрах пока не добавлены полные описания"; легенда: "- приватная
карточка"): отсутствие INT = 10 = Tier 2, а не овощ Tier 0.
"""
import re
from typing import List, Optional

DMG_CANON_TRIGGERS = [
    ('bludgeoning', ['дроб', 'bludgeon']),
    ('piercing',    ['колю', 'пронз', 'pierc']),
    ('slashing',    ['руб', 'slash']),
    ('acid',        ['кисл', 'acid']),
    ('fire',        ['огон', 'огн', 'fire']),
    ('cold',        ['хол', 'cold']),
    ('lightning',   ['электр', 'молн', 'lightn']),
    ('thunder',     ['гром', 'thund']),
    ('poison',      ['яд', 'poison']),
    ('necrotic',    ['некрот', 'necrot']),
    ('radiant',     ['излуч', 'сия', 'radiant']),
    ('psychic',     ['псих', 'psychic']),
    ('force',       ['силов', 'force']),
]

TIER_NAMES = {0: 'Рефлекторный', 1: 'Инстинктивный', 2: 'Тактический',
              3: 'Оптимизирующий', 4: 'Стратегический'}


def dmg_canon(s) -> str:
    if not s:
        return ''
    low = str(s).lower()
    for canon, triggs in DMG_CANON_TRIGGERS:
        if any(t in low for t in triggs):
            return canon
    return low.strip()


_DIE_AVG = {'d4': 2.5, 'd6': 3.5, 'd8': 4.5, 'd10': 5.5, 'd12': 6.5, 'd20': 10.5}


def _avg_dice(dtype: str) -> float:
    m = re.search(r'd(\d+)', str(dtype or ''))
    if not m:
        return 0.0
    return _DIE_AVG.get('d' + m.group(1), (int(m.group(1)) + 1) / 2.0)


def tier_from_int(int_score) -> int:
    if int_score is None:
        return 2
    try:
        v = int(int_score)
    except (TypeError, ValueError):
        return 2
    if v <= 3:
        return 0
    if v <= 7:
        return 1
    if v <= 11:
        return 2
    if v <= 15:
        return 3
    return 4


class Decision:
    __slots__ = ('target', 'attack', 'move_intent', 'target_dist_ft', 'tier', 'rationale')

    def __init__(self, target, attack, move_intent, target_dist_ft, tier, rationale=''):
        self.target = target
        self.attack = attack
        self.move_intent = move_intent
        self.target_dist_ft = target_dist_ft
        self.tier = tier
        self.rationale = rationale


class DecisionEngine:
    """Stateless-мозг + журнал объяснимости (self._round_log)."""

    def __init__(self):
        self._round_log: List[dict] = []

    # ---------- жизненный цикл журнала ----------
    def begin_round(self):
        """Сброс буфера на новый раунд. Вызывается из BattleLogic._run_round_inner
        (единственная строка-крючок в боевом ядре)."""
        self._round_log = []

    def get_round_log(self):
        """Копия снимков текущего раунда для окна анализа."""
        return list(self._round_log)

    def _log(self, **kw):
        self._round_log.append(kw)

    # ---------- главный вход ----------
    def decide(self, attacker, sides, ignore):
        from battle_strategies import distance_ft_between
        int_score = (attacker.ability_scores or {}).get('int')
        tier = tier_from_int(int_score)
        arch = attacker.strategy.__class__.__name__

        target = attacker.strategy.select_target(attacker, sides, ignore)
        if target is None:
            self._log(unit=attacker.name, side=attacker.side, int_score=int_score,
                      tier=tier, tier_name=TIER_NAMES[tier], archetype=arch,
                      target_name=None, target_reason='нет живых целей',
                      attack_name=None, attack_reason='', candidates=[],
                      move_intent='approach', move_reason='', multiattack=False,
                      rationale='')
            return Decision(None, None, 'approach', 5, tier, '')

        target_reason = f'архетип {arch} выбрал цель'
        if tier >= 2 and self._all_immune(attacker, target):
            alt = self._first_not_fully_immune(attacker, sides, ignore, skip=target)
            if alt is not None:
                target_reason = (f'архетип {arch} выбрал {target.name}, но весь арсенал '
                                 f'иммунен -> A5 переключил на {alt.name}')
                target = alt
            else:
                target_reason = (f'архетип {arch} выбрал {target.name}; A5: альтернатив '
                                 f'не найдено, бьём иммунного (выбора нет)')

        # Мультиатака: B4-распределение off в v1
        if getattr(attacker, 'multiattack', None):
            strikes_desc = ' + '.join(f"{s['attack']}×{s.get('count', 1)}"
                                      for s in attacker.multiattack)
            self._log(unit=attacker.name, side=attacker.side, int_score=int_score,
                      tier=tier, tier_name=TIER_NAMES[tier], archetype=arch,
                      target_name=target.name, target_reason=target_reason,
                      attack_name=None, attack_reason=f'мультиатака: {strikes_desc}',
                      candidates=[], move_intent='approach', move_reason='',
                      multiattack=True, rationale='')
            return Decision(target, None, 'approach', 5, tier, '')

        # Tier 0: полный делегат
        if tier == 0:
            self._log(unit=attacker.name, side=attacker.side, int_score=int_score,
                      tier=tier, tier_name=TIER_NAMES[tier], archetype=arch,
                      target_name=target.name, target_reason=target_reason,
                      attack_name=None,
                      attack_reason=f'Tier 0: решение полностью у архетипа {arch}, '
                                    f'мозг не вмешивается',
                      candidates=[], move_intent='approach', move_reason='',
                      multiattack=False, rationale='')
            return Decision(target, None, 'approach', 5, tier, '')

        # Tier >= 1: B1 (+B2 tier>=2, +B3 tier>=3) + C1/hold
        dist_now = distance_ft_between(attacker, target)
        attack, reason, candidates = self._pick_attack(attacker, target, tier, dist_now)
        if attack is None:
            self._log(unit=attacker.name, side=attacker.side, int_score=int_score,
                      tier=tier, tier_name=TIER_NAMES[tier], archetype=arch,
                      target_name=target.name, target_reason=target_reason,
                      attack_name=None, attack_reason=reason or 'нет доступных атак',
                      candidates=candidates, move_intent='approach', move_reason='',
                      multiattack=False, rationale=reason)
            return Decision(target, None, 'approach', 5, tier, reason)

        reach = getattr(attack, 'range_ft', 5)
        move_intent = 'approach'
        move_reason = f'подойти на {reach} фт (дистанция {dist_now:.0f})'
        if reach > 5 and dist_now <= reach and self._should_hold(attacker, target, dist_now):
            move_intent = 'hold'
            why = []
            if attacker.max_hp and attacker.hp / attacker.max_hp < 0.5:
                why.append(f'ранен ({attacker.hp}/{attacker.max_hp})')
            if any(getattr(a, 'range_ft', 5) <= 5 for a in getattr(target, 'attacks', [])):
                why.append('враг опасен в melee')
            move_reason = (f'держит дистанцию: {attack.name} достаёт с {dist_now:.0f} фт '
                           f'(reach {reach}), и ' + ' + '.join(why))
            reason = (reason + '; ' if reason else '') + 'держит дистанцию (стреляет издалека)'

        self._log(unit=attacker.name, side=attacker.side, int_score=int_score,
                  tier=tier, tier_name=TIER_NAMES[tier], archetype=arch,
                  target_name=target.name, target_reason=target_reason,
                  attack_name=attack.name, attack_reason=reason,
                  candidates=candidates, move_intent=move_intent,
                  move_reason=move_reason, multiattack=False, rationale=reason)
        return Decision(target, attack, move_intent, reach, tier, reason)

    # ---------- A5 ----------
    def _all_immune(self, attacker, target) -> bool:
        imm = {dmg_canon(x) for x in (getattr(target, 'immunities', []) or [])}
        if not imm:
            return False
        for a in attacker.attacks:
            if dmg_canon(getattr(a, 'damage_type', '')) not in imm:
                return False
        return True

    def _first_not_fully_immune(self, attacker, sides, ignore, skip):
        for side_idx, side_enemies in enumerate(sides):
            if side_idx == attacker.side or side_idx in ignore \
                    or side_idx in getattr(attacker, 'ignore_sides', set()):
                continue
            for e in side_enemies:
                if e.alive and e is not skip and not self._all_immune(attacker, e):
                    return e
        return None

    # ---------- B1/B2/B3 + сбор кандидатов ----------
    def _pick_attack(self, attacker, target, tier, dist_now):
        """Возвращает (best, reason, candidates). candidates - объяснительный список
        для окна анализа: каждая атака с reach/типом/eff/EV и причиной отсечения."""
        use_defense = tier >= 2
        use_hit = tier >= 3
        imm = {dmg_canon(x) for x in (getattr(target, 'immunities', []) or [])} if use_defense else set()
        res = {dmg_canon(x) for x in (getattr(target, 'resistances', []) or [])} if use_defense else set()
        ac = getattr(target, 'ac', 10)

        def metrics(a):
            c = dmg_canon(getattr(a, 'damage_type', ''))
            eff = 1.0
            if use_defense:
                eff = 0.0 if c in imm else (0.5 if c in res else 1.0)
            avg = a.damage_dice_count * _avg_dice(a.damage_dice_type) + a.damage_modifier
            if use_hit:
                p_hit = max(0.05, min(0.95, (21 - max(1, ac - a.attack_bonus)) / 20.0))
                return avg * p_hit * eff, eff
            return avg * eff, eff

        reachable = [a for a in attacker.attacks if getattr(a, 'range_ft', 5) >= dist_now]
        pool, prefer_far = (reachable, False) if reachable else (list(attacker.attacks), True)

        best, best_ev, best_eff, best_reach = None, -1.0, -1.0, None
        candidates = []
        for a in attacker.attacks:
            r = getattr(a, 'range_ft', 5)
            ev, eff = metrics(a)
            in_pool = a in pool
            if not in_pool:
                rej = f'не достаёт с {dist_now:.0f} фт (reach {r}) [B1]'
            elif eff == 0.0 and use_defense:
                rej = 'цель иммунна к этому типу [B2]'
            else:
                rej = ''
            chosen = False
            if in_pool:
                if best is None:
                    better = True
                else:
                    pri_new, pri_old = (1 if eff > 0 else 0), (1 if best_eff > 0 else 0)
                    if pri_new != pri_old:
                        better = pri_new > pri_old
                    elif abs(ev - best_ev) > 1e-9:
                        better = ev > best_ev
                    else:
                        better = (r < best_reach) if not prefer_far else (r > best_reach)
                if better:
                    if best is not None:
                        # прежний best теперь не chosen - помечаем в candidates ниже
                        pass
                    best, best_ev, best_eff, best_reach = a, ev, eff, r
            candidates.append({'name': a.name, 'reach': r,
                               'dmg_type': getattr(a, 'damage_type', '') or '—',
                               'eff': round(eff, 2), 'ev': round(ev, 1),
                               'reject': rej})
        # финальная пометка chosen (после цикла, т.к. best мог смениться)
        if best is not None:
            for cd in candidates:
                if cd['name'] == best.name:
                    cd['chosen'] = True
                    if cd['reject']:
                        cd['reject'] = ''
        reason = ''
        if best is not None:
            c = dmg_canon(getattr(best, 'damage_type', ''))
            if use_defense and best_eff == 0.0:
                reason = f'весь арсенал иммунен цели ({getattr(best, "damage_type", "")})'
            elif use_defense and 0 < best_eff < 1.0:
                reason = f'цель сопротивляется {getattr(best, "damage_type", "")} (урон пополам) [B2]'
            elif use_hit:
                reason = f'макс. EV с учётом шанса попадания [B3]'
        return best, reason, candidates

    # ---------- hold ----------
    def _should_hold(self, attacker, target, dist_now) -> bool:
        if attacker.max_hp and attacker.hp / attacker.max_hp < 0.5:
            return True
        for a in getattr(target, 'attacks', []):
            if getattr(a, 'range_ft', 5) <= 5:
                return True
        return False