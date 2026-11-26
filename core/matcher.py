from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
from typing import Iterable

from config import (
    CommentTemplates,
    DEFAULT_SETTINGS,
    MatcherSettings,
    RowStatus,
    find_conflicting_directions,
)
from core.normalizer import canonical_code_key, normalize_text
from loaders.base import ReferenceItem
from loaders.order_loader import OrderItem

try:
    from rapidfuzz import fuzz  # type: ignore

    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover
    fuzz = None
    _HAS_RAPIDFUZZ = False


_EXCLUSION_TITLES: dict[str, str] = {
    "литье": "Литьё",
    "поковка": "Поковка",
    "заготовка": "Заготовка",
    "полуфабрикат": "Полуфабрикат",
    "оснастка": "Оснастка",
}

_SUFFIX_TAIL_RE = re.compile(r"(?:-\d{1,3}|[А-ЯA-Z]{1,2})$")


@dataclass
class MatchCandidate:
    item: ReferenceItem
    matched_code: str | None
    match_kind: str  # "exact" | "base_suffix" | "fuzzy"
    score: float
    is_alternative_code: bool = False


@dataclass
class MatchResult:
    """Итог проверки одной позиции заявки по прайсу, складу и (опционально) плану производства."""

    order_item: OrderItem
    status: RowStatus
    comment: str

    price: float | int | None = None
    price_row: int | None = None
    price_sheet: str | None = None
    price_match_kind: str | None = None

    stock_qty: float | int | None = None
    stock_row: int | None = None
    stock_sheet: str | None = None
    stock_match_kind: str | None = None

    prod_plan_qty: float | int | None = None
    prod_plan_row: int | None = None

    price_candidates: list[MatchCandidate] = field(default_factory=list)
    stock_candidates: list[MatchCandidate] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def _clamp_pct(score: float) -> float:
    return float(max(0, min(100, int(round(score)))))


def _format_pct(score: float) -> int:
    return int(max(0, min(100, round(score))))


def _code_key(raw_or_norm: str | None) -> str:
    return canonical_code_key(raw_or_norm)


def _split_canonical_base_suffix(code_key: str) -> tuple[str, str]:
    """Разделяет каноничный ключ кода на базовую часть и хвостовой суффикс (если он выделяется)."""
    if not code_key:
        return "", ""
    m = _SUFFIX_TAIL_RE.search(code_key)
    if not m:
        return code_key, ""
    base = code_key[: m.start()]
    suffix = m.group(0)
    if len(base) < 4:
        return code_key, ""
    return base, suffix


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if _HAS_RAPIDFUZZ and fuzz is not None:
        return _clamp_pct(float(fuzz.token_set_ratio(a, b)))
    return _clamp_pct(float(SequenceMatcher(None, a, b).ratio() * 100.0))


def _code_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ka, kb = _code_key(a), _code_key(b)
    if not ka or not kb:
        return 0.0
    if _HAS_RAPIDFUZZ and fuzz is not None:
        return _clamp_pct(float(fuzz.ratio(ka, kb)))
    return _clamp_pct(float(SequenceMatcher(None, ka, kb).ratio() * 100.0))


def _has_exclusion(item: ReferenceItem) -> bool:
    return bool(item.exclusion_flags)


def _format_rows(items: Iterable[ReferenceItem]) -> str:
    rows = sorted({str(it.source_row) for it in items if it.source_row is not None})
    return ", ".join(rows)


def _format_fuzzy_candidates(candidates: list[MatchCandidate]) -> str:
    labels = [
        f"{c.matched_code or (c.item.raw_text or '')[:35]} (стр. {c.item.source_row}, {_format_pct(c.score)}%)"
        for c in candidates
    ]
    return "; ".join(labels)


def _find_exact_matches(
    order_item: OrderItem,
    ref_items: list[ReferenceItem],
) -> list[MatchCandidate]:
    """Ищет точные совпадения по каноничному ключу кода: сначала основные, затем альтернативные."""
    if not order_item.codes or not ref_items:
        return []

    by_code: dict[str, list[tuple[ReferenceItem, str]]] = {}
    for ref in ref_items:
        for c in ref.codes:
            k = _code_key(c.normalized or c.display)
            if k:
                by_code.setdefault(k, []).append((ref, c.display))

    ordered_order_codes = sorted(
        order_item.codes,
        key=lambda c: (1 if c.is_alternative else 0),
    )

    found: list[MatchCandidate] = []
    seen_ref_ids: set[int] = set()

    for oc in ordered_order_codes:
        ok = _code_key(oc.normalized or oc.display)
        if not ok:
            continue
        hits = by_code.get(ok, [])
        for ref, disp in hits:
            if id(ref) in seen_ref_ids:
                continue
            seen_ref_ids.add(id(ref))
            found.append(
                MatchCandidate(
                    item=ref,
                    matched_code=disp,
                    match_kind="exact",
                    score=100.0,
                    is_alternative_code=oc.is_alternative,
                )
            )
        if found and not oc.is_alternative:
            break

    return found


def _find_base_suffix_matches(
    order_item: OrderItem,
    ref_items: list[ReferenceItem],
) -> list[MatchCandidate]:
    """Ищет совпадения по базовому каноничному ключу при другом суффиксе."""
    if not order_item.codes or not ref_items:
        return []

    by_base: dict[str, list[tuple[ReferenceItem, str, str]]] = {}
    for ref in ref_items:
        for c in ref.codes:
            rk = _code_key(c.normalized or c.display)
            if not rk:
                continue
            r_base, r_suf = _split_canonical_base_suffix(rk)
            if c.base:
                cb = _code_key(c.base)
                if len(cb) >= 4:
                    by_base.setdefault(cb, []).append((ref, c.display, c.suffix or r_suf))
            if len(r_base) >= 4 and r_base != _code_key(c.base):
                by_base.setdefault(r_base, []).append((ref, c.display, r_suf))

    ordered_order_codes = sorted(
        order_item.codes,
        key=lambda c: (1 if c.is_alternative else 0),
    )

    found: list[MatchCandidate] = []
    seen_ref_ids: set[int] = set()

    for oc in ordered_order_codes:
        ok = _code_key(oc.normalized or oc.display)
        if not ok:
            continue
        o_base, o_suf = _split_canonical_base_suffix(ok)
        cand_base = _code_key(oc.base) if oc.base else o_base
        ord_suf = oc.suffix or o_suf
        if not cand_base or len(cand_base) < 4:
            continue

        hits = by_base.get(cand_base, [])
        for ref, disp, ref_suf in hits:
            if id(ref) in seen_ref_ids:
                continue
            if (ord_suf or "") == (ref_suf or ""):
                continue
            seen_ref_ids.add(id(ref))
            found.append(
                MatchCandidate(
                    item=ref,
                    matched_code=disp,
                    match_kind="base_suffix",
                    score=92.0,
                    is_alternative_code=oc.is_alternative,
                )
            )
        if found and not oc.is_alternative:
            break

    return found


def _find_fuzzy_matches(
    order_item: OrderItem,
    ref_items: list[ReferenceItem],
    settings: MatcherSettings,
) -> list[MatchCandidate]:
    """Нечёткий поиск по каноничным ключам кодов и наименованиям."""
    if not ref_items:
        return []

    order_codes_keys = [_code_key(c.normalized or c.display) for c in order_item.codes]
    order_codes_keys = [k for k in order_codes_keys if k]
    order_norm_text = order_item.norm_text or normalize_text(order_item.raw_text, lower=True)

    scored: list[tuple[float, MatchCandidate]] = []
    for ref in ref_items:
        best_score = 0.0
        best_code: str | None = None

        if order_codes_keys and ref.codes:
            for ok in order_codes_keys:
                for rc in ref.codes:
                    rk = _code_key(rc.normalized or rc.display)
                    if not rk:
                        continue
                    s = _code_similarity(ok, rk)
                    if s > best_score:
                        best_score = s
                        best_code = rc.display

        if best_score < settings.fuzzy_code_min_score and order_norm_text and ref.norm_text:
            name_score = _similarity(order_norm_text, ref.norm_text)
            if name_score >= settings.fuzzy_name_min_score and name_score > best_score:
                best_score = name_score
                best_code = ref.codes[0].display if ref.codes else None

        threshold = (
            settings.fuzzy_code_min_score if best_code else settings.fuzzy_name_min_score
        )
        if best_score >= threshold:
            clamped = _clamp_pct(best_score)
            scored.append(
                (
                    clamped,
                    MatchCandidate(
                        item=ref,
                        matched_code=best_code,
                        match_kind="fuzzy",
                        score=clamped,
                        is_alternative_code=False,
                    ),
                )
            )

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [cand for _, cand in scored[: settings.max_fuzzy_candidates]]


def _select_price_match(
    order_item: OrderItem,
    price_items: list[ReferenceItem],
    settings: MatcherSettings,
) -> tuple[
    list[MatchCandidate],
    float | int | None,
    int | None,
    str | None,
    str | None,
    list[str],
    list[str],
]:
    messages: list[str] = []
    flags: list[str] = []

    exact = _find_exact_matches(order_item, price_items)
    if exact:
        candidates = exact
        match_kind = "exact"
    else:
        base_hits = _find_base_suffix_matches(order_item, price_items)
        if base_hits:
            candidates = base_hits
            match_kind = "base_suffix"
        else:
            fuzzy_hits = _find_fuzzy_matches(order_item, price_items, settings)
            messages.append(CommentTemplates.NO_PRICE_MATCH)
            if fuzzy_hits:
                messages.append(
                    CommentTemplates.FUZZY_CANDIDATES_PRICE.format(
                        candidates=_format_fuzzy_candidates(fuzzy_hits)
                    )
                )
                flags.append("price_fuzzy_only")
                return fuzzy_hits, None, None, None, "fuzzy", messages, flags

            flags.append("price_not_found")
            return [], None, None, None, None, messages, flags

    primary = candidates[0].item
    price_row = primary.source_row
    price_sheet = primary.sheet_name

    if match_kind == "base_suffix":
        flags.append("price_suffix_mismatch")
        messages.append(
            CommentTemplates.SUFFIX_MISMATCH_PRICE.format(
                code=candidates[0].matched_code or (primary.raw_code or primary.raw_text or ""),
                row=primary.source_row,
            )
        )

    for cand in candidates:
        conflicts = find_conflicting_directions(order_item.direction_flags, cand.item.direction_flags)
        for ord_d, ref_d in conflicts:
            flags.append("price_direction_conflict")
            messages.append(
                CommentTemplates.DIRECTION_CONFLICT_PRICE.format(
                    ord_dir=ord_d,
                    ref_dir=ref_d,
                    row=cand.item.source_row,
                )
            )

    for cand in candidates:
        if _has_exclusion(cand.item):
            ex_key = cand.item.exclusion_flags[0]
            flags.append(f"price_exclusion_{ex_key}")
            messages.append(
                CommentTemplates.EXCLUDED_PRICE_ITEM.format(
                    kind_title=_EXCLUSION_TITLES.get(ex_key, ex_key),
                    row=cand.item.source_row,
                )
            )

    if len(candidates) > 1:
        rows_str = _format_rows(c.item for c in candidates)
        prices = {c.item.price for c in candidates if c.item.price is not None}
        if len(prices) == 1:
            flags.append("price_dup_same_price")
            messages.append(CommentTemplates.DUPLICATE_PRICE_SAME_PRICE.format(rows=rows_str))
        elif len(prices) > 1:
            flags.append("price_dup_diff_price")
            messages.append(CommentTemplates.DUPLICATE_PRICE_DIFF_PRICE.format(rows=rows_str))

    if primary.is_made_to_order or not primary.has_price_column:
        flags.append("price_made_to_order")
        messages.append(CommentTemplates.MADE_TO_ORDER_SHEET)
        return candidates, None, price_row, price_sheet, match_kind, messages, flags

    if primary.is_novelty:
        flags.append("price_novelty")
        messages.append(CommentTemplates.NOVELTY_SHEET)

    if primary.price is None or primary.price == 0:
        if settings.treat_zero_price_as_unconfirmed:
            flags.append("price_zero_or_missing")
            messages.append(CommentTemplates.ZERO_OR_MISSING_PRICE)
            return candidates, None, price_row, price_sheet, match_kind, messages, flags

    return candidates, primary.price, price_row, price_sheet, match_kind, messages, flags


def _select_stock_match(
    order_item: OrderItem,
    stock_items: list[ReferenceItem],
    settings: MatcherSettings,
) -> tuple[
    list[MatchCandidate],
    float | int | None,
    int | None,
    str | None,
    str | None,
    list[str],
    list[str],
]:
    messages: list[str] = []
    flags: list[str] = []

    exact = _find_exact_matches(order_item, stock_items)
    if exact:
        candidates = exact
        match_kind = "exact"
    else:
        base_hits = _find_base_suffix_matches(order_item, stock_items)
        if base_hits:
            candidates = base_hits
            match_kind = "base_suffix"
        else:
            fuzzy_hits = _find_fuzzy_matches(order_item, stock_items, settings)
            messages.append(CommentTemplates.NO_STOCK_MATCH)
            if fuzzy_hits:
                messages.append(
                    CommentTemplates.FUZZY_CANDIDATES_STOCK.format(
                        candidates=_format_fuzzy_candidates(fuzzy_hits)
                    )
                )
                flags.append("stock_fuzzy_only")
                return fuzzy_hits, None, None, None, "fuzzy", messages, flags

            flags.append("stock_not_found")
            return [], None, None, None, None, messages, flags

    excluded_cands = [c for c in candidates if _has_exclusion(c.item)]
    ready_cands = [c for c in candidates if not _has_exclusion(c.item)]

    for ec in excluded_cands:
        ex_key = ec.item.exclusion_flags[0]
        flags.append(f"stock_excluded_{ex_key}")
        messages.append(
            CommentTemplates.EXCLUDED_STOCK_ITEM.format(
                kind_title=_EXCLUSION_TITLES.get(ex_key, ex_key),
                row=ec.item.source_row,
            )
        )

    if not ready_cands:
        first_ex = excluded_cands[0].item
        return (
            candidates,
            None,
            first_ex.source_row,
            first_ex.sheet_name,
            match_kind,
            messages,
            flags,
        )

    primary_ready = ready_cands[0].item
    stock_row = primary_ready.source_row
    stock_sheet = primary_ready.sheet_name

    if match_kind == "base_suffix":
        flags.append("stock_suffix_mismatch")
        messages.append(
            CommentTemplates.SUFFIX_MISMATCH_STOCK.format(
                code=ready_cands[0].matched_code or (primary_ready.raw_code or primary_ready.raw_text or ""),
                row=primary_ready.source_row,
            )
        )

    has_dir_conflict = False
    for rc in ready_cands:
        conflicts = find_conflicting_directions(order_item.direction_flags, rc.item.direction_flags)
        for ord_d, ref_d in conflicts:
            has_dir_conflict = True
            flags.append("stock_direction_conflict")
            messages.append(
                CommentTemplates.DIRECTION_CONFLICT_STOCK.format(
                    ord_dir=ord_d,
                    ref_dir=ref_d,
                    row=rc.item.source_row,
                )
            )

    if len(ready_cands) > 1:
        rows_str = _format_rows(c.item for c in ready_cands)
        flags.append("stock_duplicates")
        messages.append(CommentTemplates.DUPLICATE_STOCK_ROWS.format(rows=rows_str))

    if has_dir_conflict:
        return candidates, None, stock_row, stock_sheet, match_kind, messages, flags

    if len(ready_cands) > 1 and not settings.sum_duplicate_stock_by_default:
        return candidates, None, stock_row, stock_sheet, match_kind, messages, flags

    qty_values = [c.item.qty for c in ready_cands if c.item.qty is not None]
    if not qty_values:
        total_qty: float | int | None = None
    else:
        s = sum(qty_values)
        total_qty = int(s) if float(s).is_integer() else round(float(s), 6)

    if total_qty == 0:
        flags.append("stock_zero")
        messages.append(CommentTemplates.ZERO_STOCK)

    return candidates, total_qty, stock_row, stock_sheet, match_kind, messages, flags


def _compute_row_status(
    *,
    order_item: OrderItem,
    price: float | int | None,
    stock_qty: float | int | None,
    flags: list[str],
) -> RowStatus:
    """
    Определяет итоговый статус строки для раскраски в Excel:
    - attention: реальные конфликты/риски (направления, заготовка/оснастка, ТОЛЬКО ДЛЯ СБОРКИ);
    - not_found: не найдено ни в прайсе, ни в остатках (включая только нечёткие подсказки);
    - warning: частичные совпадения, суффиксы, дубли, нулевой остаток или неполные данные;
    - ok: подтверждены цена и ненулевой остаток без предупреждений и конфликтов.
    """
    attention_flags = {
        "order_only_for_assembly",
        "price_direction_conflict",
        "stock_direction_conflict",
    }
    if any(f in attention_flags or f.startswith("stock_excluded_") for f in flags):
        return RowStatus.ATTENTION

    if price is None and stock_qty is None:
        return RowStatus.NOT_FOUND

    if flags:
        return RowStatus.WARNING

    return RowStatus.OK


def match_order_item(
    order_item: OrderItem,
    *,
    price_items: list[ReferenceItem],
    stock_items: list[ReferenceItem],
    prod_plan_items: list[ReferenceItem] | None = None,
    settings: MatcherSettings = DEFAULT_SETTINGS,
) -> MatchResult:
    messages: list[str] = []
    flags: list[str] = []

    if "только_для_сборки" in order_item.note_flags:
        flags.append("order_only_for_assembly")
        messages.append(CommentTemplates.ONLY_FOR_ASSEMBLY)

    p_cands, price, p_row, p_sheet, p_kind, p_msgs, p_flags = _select_price_match(
        order_item, price_items, settings
    )
    s_cands, stock_qty, s_row, s_sheet, s_kind, s_msgs, s_flags = _select_stock_match(
        order_item, stock_items, settings
    )

    messages.extend(p_msgs)
    messages.extend(s_msgs)
    flags.extend(p_flags)
    flags.extend(s_flags)

    plan_qty: float | int | None = None
    plan_row: int | None = None
    if prod_plan_items:
        plan_hits = _find_exact_matches(order_item, prod_plan_items)
        if plan_hits:
            top_plan = plan_hits[0].item
            plan_qty = top_plan.qty
            plan_row = top_plan.source_row
            if plan_qty is not None and top_plan.source_row is not None:
                messages.append(
                    CommentTemplates.PROD_PLAN_INFO.format(
                        qty=plan_qty,
                        unit=order_item.raw_unit or "шт.",
                        row=top_plan.source_row,
                    )
                )

    status = _compute_row_status(
        order_item=order_item,
        price=price,
        stock_qty=stock_qty,
        flags=flags,
    )

    unique_messages = list(dict.fromkeys(m.strip() for m in messages if m and m.strip()))
    comment = " ".join(unique_messages)

    return MatchResult(
        order_item=order_item,
        status=status,
        comment=comment,
        price=price,
        price_row=p_row,
        price_sheet=p_sheet,
        price_match_kind=p_kind,
        stock_qty=stock_qty,
        stock_row=s_row,
        stock_sheet=s_sheet,
        stock_match_kind=s_kind,
        prod_plan_qty=plan_qty,
        prod_plan_row=plan_row,
        price_candidates=p_cands,
        stock_candidates=s_cands,
        flags=list(dict.fromkeys(flags)),
    )


def match_order(
    order_items: list[OrderItem],
    *,
    price_items: list[ReferenceItem],
    stock_items: list[ReferenceItem],
    prod_plan_items: list[ReferenceItem] | None = None,
    settings: MatcherSettings = DEFAULT_SETTINGS,
) -> list[MatchResult]:
    return [
        match_order_item(
            item,
            price_items=price_items,
            stock_items=stock_items,
            prod_plan_items=prod_plan_items,
            settings=settings,
        )
        for item in order_items
    ]