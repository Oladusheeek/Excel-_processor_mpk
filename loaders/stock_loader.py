from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.normalizer import clean_number, clean_optional_str, normalize_text
from loaders.base import ReferenceItem, build_reference_item_from_parsed, load_workbook_sheets


@dataclass
class StockColumnInfo:
    col_idx: int
    header_raw: str
    parsed_date: date | None
    is_balance: bool


@dataclass
class StockLoadResult:
    items: list[ReferenceItem]
    tooling_items: list[ReferenceItem]
    sheets_processed: list[str]
    skipped_sheets: list[tuple[str, str]]
    selected_date_columns: dict[str, str]


_DATE_TOKEN_RE = re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b")
_BALANCE_HINT_RE = re.compile(r"(остат\w*|отат\w*|налич\w*|кол-?во|количество|итог\w*\s*ост)", re.IGNORECASE)
_MOVEMENT_ONLY_RE = re.compile(r"(приход|расход|прих\.|расх\.)", re.IGNORECASE)
_NAME_COL_RE = re.compile(r"^(наименование|номенклатура|товар\w*|позиция|материал)\b", re.IGNORECASE)
_CODE_COL_RE = re.compile(r"^(каталожн\w*\s*номер|артикул|код|шифр)\b", re.IGNORECASE)
_UNIT_COL_RE = re.compile(r"^(ед\.?\s*изм\.?|единица)\b", re.IGNORECASE)


def _parse_date_value(val: Any) -> date | None:
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = clean_optional_str(val)
    if not s:
        return None
    m = _DATE_TOKEN_RE.search(s)
    if not m:
        return None
    token = m.group(1).replace("/", ".").replace("-", ".")
    for fmt in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def _parse_target_date(target_date: date | datetime | str | None) -> date | None:
    if target_date is None:
        return None
    if isinstance(target_date, datetime):
        return target_date.date()
    if isinstance(target_date, date):
        return target_date
    s = clean_optional_str(target_date)
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return _parse_date_value(s)


def _classify_stock_sheet(sheet_name: str, *, include_tooling: bool) -> tuple[str, str | None]:
    """
    Возвращает (kind, skip_reason):
    - kind: "stock" | "tooling" | "skip"
    """
    low = normalize_text(sheet_name, lower=True)
    if any(k in low for k in ("оснаст", "пресс-форм", "штамп", "модельн")):
        return ("tooling" if include_tooling else "skip"), "tooling_sheet"
    if any(k in low for k in ("свод", "настройк", "справочн", "лист1", "инструкц")) and "склад" not in low:
        return "skip", "service_or_summary_sheet"
    return "stock", None


def _infer_name_column_from_data(
    rows: list[tuple[int, list[Any]]],
    *,
    header_row_num: int,
    max_col_exclusive: int,
) -> int:
    """
    Определяет колонку с наименованиями по реальным строкам ниже шапки
    (актуально, когда в шапке заголовок над наименованием пустой, а в col 0 стоит 'товары'/'покупные').
    """
    data_rows = [(r, vals) for r, vals in rows if r > header_row_num][:40]
    if not data_rows or max_col_exclusive <= 1:
        return 0

    best_col = 0
    best_score = (-1, -1.0)
    for col_idx in range(max_col_exclusive):
        texts: list[str] = []
        for _, vals in data_rows:
            if col_idx >= len(vals):
                continue
            s = clean_optional_str(vals[col_idx])
            if s and clean_number(s) is None and len(s) > 2:
                texts.append(s)
        avg_len = (sum(len(t) for t in texts) / len(texts)) if texts else 0.0
        score = (len(texts), avg_len)
        if score > best_score:
            best_score = score
            best_col = col_idx

    return best_col


def _find_header_and_columns(
    rows: list[tuple[int, list[Any]]],
    target_date: date | None,
) -> tuple[int, int, int | None, int | None, str]:
    """
    Определяет строку шапки и индексы колонок:
    (header_row_num, name_idx, code_idx, qty_idx, selected_col_label)
    """
    best_header_row = 0
    best_name_idx: int | None = None
    best_code_idx: int | None = None
    best_qty_idx: int | None = None
    best_first_data_col = 2
    best_score = -1

    for row_num, vals in rows[:15]:
        name_idx: int | None = None
        code_idx: int | None = None
        balance_cols: list[StockColumnInfo] = []
        fallback_num_cols: list[int] = []
        first_metric_col: int | None = None

        for idx, val in enumerate(vals):
            s = clean_optional_str(val)
            d = _parse_date_value(val)
            if not s:
                continue

            is_mov_only = bool(_MOVEMENT_ONLY_RE.search(s)) and ("остат" not in s.lower()) and ("отат" not in s.lower())
            is_bal = bool(_BALANCE_HINT_RE.search(s)) or (d is not None and not is_mov_only)

            if is_bal or is_mov_only:
                if first_metric_col is None:
                    first_metric_col = idx

            if name_idx is None and _NAME_COL_RE.search(s) and s.lower() != "товары":
                name_idx = idx
            elif code_idx is None and _CODE_COL_RE.search(s):
                code_idx = idx
            elif _UNIT_COL_RE.search(s):
                continue
            elif is_bal and not is_mov_only:
                balance_cols.append(
                    StockColumnInfo(
                        col_idx=idx,
                        header_raw=s,
                        parsed_date=d,
                        is_balance=True,
                    )
                )
            elif not is_mov_only and not _NAME_COL_RE.search(s) and not _CODE_COL_RE.search(s):
                fallback_num_cols.append(idx)

        score = (2 if name_idx is not None else 0) + (1 if code_idx is not None else 0) + (3 if balance_cols else 0)
        if score > best_score and (name_idx is not None or balance_cols):
            best_score = score
            best_header_row = row_num
            best_name_idx = name_idx
            best_code_idx = code_idx
            if first_metric_col is not None:
                best_first_data_col = first_metric_col

            if balance_cols:
                dated = [c for c in balance_cols if c.parsed_date is not None]
                if target_date and dated:
                    exact = [c for c in dated if c.parsed_date == target_date]
                    if exact:
                        chosen = exact[-1]
                    else:
                        earlier = [c for c in dated if c.parsed_date <= target_date]
                        chosen = max(earlier, key=lambda c: c.parsed_date) if earlier else dated[-1]
                elif dated:
                    chosen = max(dated, key=lambda c: (c.parsed_date, c.col_idx))
                else:
                    chosen = balance_cols[-1]
                best_qty_idx = chosen.col_idx
            elif fallback_num_cols:
                best_qty_idx = fallback_num_cols[-1]

    if best_score <= 0:
        max_cols = max((len(vals) for _, vals in rows), default=0)
        name_idx = _infer_name_column_from_data(rows, header_row_num=0, max_col_exclusive=min(2, max_cols))
        code_idx = 1 if max_cols >= 3 and name_idx == 0 else None
        qty_idx = max_cols - 1 if max_cols >= 2 else None
        return 0, name_idx, code_idx, qty_idx, f"col_{qty_idx}" if qty_idx is not None else "none"

    if best_name_idx is None:
        best_name_idx = _infer_name_column_from_data(
            rows,
            header_row_num=best_header_row,
            max_col_exclusive=best_first_data_col,
        )

    label = "none"
    if best_qty_idx is not None:
        header_vals = next((vals for r_num, vals in rows if r_num == best_header_row), [])
        label = clean_optional_str(header_vals[best_qty_idx]) if best_qty_idx < len(header_vals) else f"col_{best_qty_idx}"

    return best_header_row, best_name_idx, best_code_idx, best_qty_idx, label


def _detect_section_row(
    vals: list[Any],
    *,
    name_idx: int,
    code_idx: int | None,
    qty: float | int | None,
) -> str | None:
    """
    Проверяет, является ли строка заголовком группы/раздела
    (например, 'покупные' в col 0 при пустых col 1 и количестве).
    """
    name_val = clean_optional_str(vals[name_idx]) if name_idx < len(vals) else None
    code_val = clean_optional_str(vals[code_idx]) if code_idx is not None and code_idx < len(vals) else None

    if qty is not None or code_val is not None:
        return None

    # Если наименование в основной колонке пустое, но в col 0 есть маркер группы ('покупные', 'собственные' и т.п.)
    if not name_val and name_idx > 0 and len(vals) > 0:
        left_val = clean_optional_str(vals[0])
        if left_val and clean_number(left_val) is None and len(left_val) <= 60:
            return left_val

    if name_val:
        low = name_val.lower().strip()
        if low.startswith(("итого", "всего", "остаток на начало", "остаток на конец")):
            return None
        if len(name_val) <= 90 and not re.search(r"\d{2,}[.\-]\d{2,}", name_val):
            return name_val

    return None


def load_stock(
    file_path: str | Path,
    *,
    target_date: date | datetime | str | None = None,
    include_tooling: bool = False,
) -> StockLoadResult:
    """
    Загружает складские остатки с листов ведомости/выгрузки.
    По умолчанию пропускает вкладки оснастки и служебные листы.
    """
    parsed_target_date = _parse_target_date(target_date)
    sheets_data = load_workbook_sheets(file_path)

    items: list[ReferenceItem] = []
    tooling_items: list[ReferenceItem] = []
    sheets_processed: list[str] = []
    skipped_sheets: list[tuple[str, str]] = []
    selected_date_columns: dict[str, str] = {}

    for sheet_name, rows in sheets_data.items():
        if not rows:
            skipped_sheets.append((sheet_name, "empty_sheet"))
            continue

        kind, skip_reason = _classify_stock_sheet(sheet_name, include_tooling=include_tooling)
        if kind == "skip":
            skipped_sheets.append((sheet_name, skip_reason or "skipped"))
            continue

        header_row_num, name_idx, code_idx, qty_idx, col_label = _find_header_and_columns(
            rows, parsed_target_date
        )
        sheets_processed.append(sheet_name)
        selected_date_columns[sheet_name] = col_label

        current_section: str | None = None
        is_tooling = kind == "tooling"

        for seq_idx, (row_num, vals) in enumerate(rows):
            if row_num <= header_row_num:
                continue

            raw_text = vals[name_idx] if name_idx < len(vals) else None
            raw_code = vals[code_idx] if code_idx is not None and code_idx < len(vals) else None
            raw_qty = vals[qty_idx] if qty_idx is not None and qty_idx < len(vals) else None

            clean_name = clean_optional_str(raw_text)
            clean_code = clean_optional_str(raw_code)
            clean_q = clean_number(raw_qty)

            section_title = _detect_section_row(
                vals,
                name_idx=name_idx,
                code_idx=code_idx,
                qty=clean_q,
            )
            if section_title:
                current_section = section_title
                continue

            if not clean_name and not clean_code and clean_q is None:
                continue

            if clean_name and clean_name.lower().strip().startswith(
                ("итого", "всего", "остаток на начало", "остаток на конец")
            ):
                continue

            item = build_reference_item_from_parsed(
                source_type="stock",
                sheet_name=sheet_name,
                source_row=row_num,
                row_index=seq_idx,
                raw_text=raw_text,
                raw_code=raw_code,
                raw_qty=raw_qty,
                section_name=current_section,
                has_price_column=False,
            )
            if is_tooling:
                tooling_items.append(item)
            else:
                items.append(item)

    return StockLoadResult(
        items=items,
        tooling_items=tooling_items,
        sheets_processed=sheets_processed,
        skipped_sheets=skipped_sheets,
        selected_date_columns=selected_date_columns,
    )