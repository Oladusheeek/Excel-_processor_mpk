from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.normalizer import clean_number, clean_optional_str, normalize_text
from loaders.base import ReferenceItem, build_reference_item_from_parsed, load_workbook_sheets


@dataclass
class PriceLoadResult:
    items: list[ReferenceItem]
    sheets_processed: list[str]
    skipped_rows: list[tuple[str, int, str]]  # (sheet_name, row_num, reason)


_NAME_HEADER_RE = re.compile(r"^(наименование|товар|позиция|номенклатура)\b", re.IGNORECASE)
_CODE_HEADER_RE = re.compile(r"^(каталожн\w*\s*номер|артикул|код)\b", re.IGNORECASE)
_PRICE_HEADER_RE = re.compile(r"^(цена|стоимость|прайс)", re.IGNORECASE)


def _classify_sheet(sheet_name: str) -> str:
    """Определяет тип листа прайса по его названию."""
    low = normalize_text(sheet_name, lower=True)
    if "новинк" in low:
        return "novelty"
    if "заказ" in low:
        return "made_to_order"
    return "main"


def _detect_columns(rows: list[tuple[int, list[Any]]], sheet_kind: str) -> tuple[int, int | None, int | None, int]:
    """
    Находит индексы колонок (name_idx, code_idx, price_idx, header_row_num).
    Если явная шапка не найдена — использует безопасные эвристики под тип листа.
    """
    for row_num, vals in rows[:15]:
        name_idx: int | None = None
        code_idx: int | None = None
        price_idx: int | None = None

        for idx, val in enumerate(vals):
            s = clean_optional_str(val)
            if not s:
                continue
            if name_idx is None and _NAME_HEADER_RE.search(s):
                name_idx = idx
            elif code_idx is None and _CODE_HEADER_RE.search(s):
                code_idx = idx
            elif price_idx is None and _PRICE_HEADER_RE.search(s):
                price_idx = idx

        if name_idx is not None or (code_idx is not None and price_idx is not None):
            return (
                name_idx if name_idx is not None else 0,
                code_idx,
                price_idx if sheet_kind != "made_to_order" else None,
                row_num,
            )

    # Фолбэк для листов без явной шапки
    max_cols = max((len(vals) for _, vals in rows), default=0)
    if sheet_kind == "made_to_order":
        return 0, (1 if max_cols > 1 else None), None, 0
    if sheet_kind == "novelty":
        return 0, (1 if max_cols > 2 else None), (max_cols - 1 if max_cols >= 2 else None), 0
    return 0, (1 if max_cols > 1 else None), (2 if max_cols > 2 else None), 0


def _is_section_header(
    vals: list[Any],
    *,
    name_idx: int,
    code_idx: int | None,
    price_idx: int | None,
) -> bool:
    """Определяет, является ли строка заголовком раздела/группы внутри прайса."""
    name_val = clean_optional_str(vals[name_idx]) if name_idx < len(vals) else None
    code_val = clean_optional_str(vals[code_idx]) if code_idx is not None and code_idx < len(vals) else None
    price_val = clean_number(vals[price_idx]) if price_idx is not None and price_idx < len(vals) else None

    if not name_val:
        return False
    if code_val is not None or price_val is not None:
        return False

    # Короткая текстовая строка без артикула и цены — обычно заголовок раздела
    low = name_val.lower()
    if low.startswith(("итого", "всего")):
        return True
    if len(name_val) <= 80 and not re.search(r"\d{2,}[.\-]\d{2,}", name_val):
        return True
    return False


def load_price_list(file_path: str | Path) -> PriceLoadResult:
    """
    Загружает прайс-лист со всех листов (основной прайс, НОВИНКИ, ИЗГОТОВЛЕНИЕ НА ЗАКАЗ),
    сохраняя исходные номера строк и признаки особенностей листов.
    """
    sheets_data = load_workbook_sheets(file_path)
    items: list[ReferenceItem] = []
    skipped_rows: list[tuple[str, int, str]] = []
    sheets_processed: list[str] = []

    for sheet_name, rows in sheets_data.items():
        if not rows:
            continue

        sheet_kind = _classify_sheet(sheet_name)
        name_idx, code_idx, price_idx, header_row_num = _detect_columns(rows, sheet_kind)
        sheets_processed.append(sheet_name)

        current_section: str | None = None
        is_made_to_order = sheet_kind == "made_to_order"
        is_novelty = sheet_kind == "novelty"
        has_price_column = not is_made_to_order and price_idx is not None

        for seq_idx, (row_num, vals) in enumerate(rows):
            if row_num <= header_row_num:
                continue

            raw_text = vals[name_idx] if name_idx < len(vals) else None
            raw_code = vals[code_idx] if code_idx is not None and code_idx < len(vals) else None
            raw_price = vals[price_idx] if price_idx is not None and price_idx < len(vals) else None

            clean_name = clean_optional_str(raw_text)
            clean_code = clean_optional_str(raw_code)
            clean_p = clean_number(raw_price) if has_price_column else None

            if clean_name is None and clean_code is None and clean_p is None:
                skipped_rows.append((sheet_name, row_num, "empty_row"))
                continue

            if clean_name and clean_name.lower().startswith(("итого", "всего")):
                skipped_rows.append((sheet_name, row_num, "total_row"))
                continue

            if _is_section_header(vals, name_idx=name_idx, code_idx=code_idx, price_idx=price_idx):
                current_section = clean_name
                skipped_rows.append((sheet_name, row_num, "section_header"))
                continue

            item = build_reference_item_from_parsed(
                source_type="price",
                sheet_name=sheet_name,
                source_row=row_num,
                row_index=seq_idx,
                raw_text=raw_text,
                raw_code=raw_code,
                raw_price=raw_price if has_price_column else None,
                section_name=current_section,
                has_price_column=has_price_column,
                is_made_to_order=is_made_to_order,
                is_novelty=is_novelty,
            )
            items.append(item)

    return PriceLoadResult(
        items=items,
        sheets_processed=sheets_processed,
        skipped_rows=skipped_rows,
    )