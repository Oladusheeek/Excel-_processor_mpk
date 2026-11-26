from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.normalizer import clean_number, clean_optional_str
from core.parser import ParsedCode, parse_row
from loaders.base import load_workbook_sheets


@dataclass
class OrderItem:
    """Нормализованная позиция заявки."""

    sheet_name: str
    source_row: int
    raw_text: str | None
    raw_code: str | None
    raw_qty: Any
    raw_unit: str | None
    raw_note: str | None
    norm_text: str
    qty: float | int | None
    section_name: str | None = None
    codes: list[ParsedCode] = field(default_factory=list)
    exclusion_flags: list[str] = field(default_factory=list)
    direction_flags: list[str] = field(default_factory=list)
    note_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    raw_cells: list[Any] = field(default_factory=list)

    @property
    def all_code_keys(self) -> list[str]:
        return [c.normalized for c in self.codes]

    @property
    def all_base_keys(self) -> list[str]:
        return [c.base for c in self.codes if c.base]


@dataclass
class OrderLoadResult:
    items: list[OrderItem]
    sheets_processed: list[str]
    skipped_rows: list[tuple[str, int, str]]  # (sheet_name, row_num, reason)


_NAME_HEADER_RE = re.compile(r"^(наименование|номенклатура|товар|позиция|деталь|материал)\b", re.IGNORECASE)
_CODE_HEADER_RE = re.compile(r"^(каталожн\w*\s*номер|артикул|код|шифр|чертеж)\b", re.IGNORECASE)
_QTY_HEADER_RE = re.compile(r"^(кол-?во|количество|потребност\w*|заявк\w*|к\s*закупк\w*)\b", re.IGNORECASE)
_UNIT_HEADER_RE = re.compile(r"^(ед\.?\s*изм\.?|единица)\b", re.IGNORECASE)
_NOTE_HEADER_RE = re.compile(r"^(примеч\w*|комментар\w*|ограничен\w*|назначен\w*|доп\.?\s*инф\w*)\b", re.IGNORECASE)


def _detect_order_columns(
    rows: list[tuple[int, list[Any]]],
) -> tuple[int, int, int | None, int | None, int | None, int | None]:
    """
    Определяет индексы колонок заявки:
    (header_row_num, name_idx, code_idx, qty_idx, unit_idx, note_idx)
    """
    for row_num, vals in rows[:15]:
        name_idx: int | None = None
        code_idx: int | None = None
        qty_idx: int | None = None
        unit_idx: int | None = None
        note_idx: int | None = None

        for idx, val in enumerate(vals):
            s = clean_optional_str(val)
            if not s:
                continue
            if name_idx is None and _NAME_HEADER_RE.search(s):
                name_idx = idx
            elif code_idx is None and _CODE_HEADER_RE.search(s):
                code_idx = idx
            elif qty_idx is None and _QTY_HEADER_RE.search(s):
                qty_idx = idx
            elif unit_idx is None and _UNIT_HEADER_RE.search(s):
                unit_idx = idx
            elif note_idx is None and _NOTE_HEADER_RE.search(s):
                note_idx = idx

        if name_idx is not None or qty_idx is not None:
            return (
                row_num,
                name_idx if name_idx is not None else 0,
                code_idx,
                qty_idx,
                unit_idx,
                note_idx,
            )

    # Фолбэк, если явная шапка не распознана: ищем первый текстовый столбец и числовой столбец количества
    max_cols = max((len(vals) for _, vals in rows), default=0)
    name_idx = 0
    best_text_col = 0
    best_text_count = -1
    for c in range(min(max_cols, 5)):
        cnt = sum(
            1
            for _, vals in rows[:40]
            if c < len(vals) and clean_optional_str(vals[c]) and clean_number(vals[c]) is None
        )
        if cnt > best_text_count:
            best_text_count = cnt
            best_text_col = c
    name_idx = best_text_col

    qty_idx = None
    for c in range(max_cols):
        if c == name_idx:
            continue
        num_cnt = sum(
            1
            for _, vals in rows[:40]
            if c < len(vals) and clean_number(vals[c]) is not None
        )
        if num_cnt >= 2:
            qty_idx = c
            break

    return 0, name_idx, None, qty_idx, None, None


def _is_order_non_item(
    name: str | None,
    code: str | None,
    qty: float | int | None,
    has_other_text: bool,
) -> str | None:
    if not name and not code and qty is None and not has_other_text:
        return "empty_row"
    if name:
        low = name.lower().strip()
        if low.startswith(("итого", "всего", "итого по заявке", "итого:")):
            return "total_row"
        if low in {"наименование", "номенклатура", "товар", "позиция"}:
            return "repeated_header"
        if not code and qty is None and len(name) <= 90 and not re.search(r"\d{2,}[.\-]\d{2,}", name):
            return "section_header"
    return None


def load_order(file_path: str | Path) -> OrderLoadResult:
    """
    Загружает файл заявки (например, ГСМ 2027 заявка.xlsx / РСМ 2027 заявка.xlsx),
    сохраняя исходные строки, очищенные количества, коды и пометки ограничений.
    """
    sheets_data = load_workbook_sheets(file_path)
    items: list[OrderItem] = []
    skipped_rows: list[tuple[str, int, str]] = []
    sheets_processed: list[str] = []

    for sheet_name, rows in sheets_data.items():
        if not rows:
            continue

        header_row_num, name_idx, code_idx, qty_idx, unit_idx, note_idx = _detect_order_columns(rows)
        sheets_processed.append(sheet_name)

        header_vals = next((vals for r_num, vals in rows if r_num == header_row_num), [])
        max_len = max((len(vals) for _, vals in rows), default=0)
        headers = [
            clean_optional_str(header_vals[i]) or f"Колонка_{i + 1}"
            if i < len(header_vals)
            else f"Колонка_{i + 1}"
            for i in range(max_len)
        ]

        current_section: str | None = None

        for seq_idx, (row_num, vals) in enumerate(rows):
            if row_num <= header_row_num:
                continue

            raw_text = vals[name_idx] if name_idx < len(vals) else None
            raw_code = vals[code_idx] if code_idx is not None and code_idx < len(vals) else None
            raw_qty = vals[qty_idx] if qty_idx is not None and qty_idx < len(vals) else None
            raw_unit = clean_optional_str(vals[unit_idx]) if unit_idx is not None and unit_idx < len(vals) else None
            raw_note = clean_optional_str(vals[note_idx]) if note_idx is not None and note_idx < len(vals) else None

            clean_name = clean_optional_str(raw_text)
            clean_code = clean_optional_str(raw_code)
            clean_q = clean_number(raw_qty)

            # Собираем дополнительный текст из прочих колонок, если примечание не в отдельном столбце
            extra_parts: list[str] = []
            for idx, val in enumerate(vals):
                if idx in {name_idx, code_idx, qty_idx, unit_idx, note_idx}:
                    continue
                s = clean_optional_str(val)
                if s and clean_number(s) is None:
                    extra_parts.append(s)

            combined_text_for_flags = " | ".join(
                p for p in [clean_name, raw_note, *extra_parts] if p
            )

            skip_reason = _is_order_non_item(
                clean_name,
                clean_code,
                clean_q,
                has_other_text=bool(raw_note or extra_parts),
            )
            if skip_reason == "section_header" and clean_name:
                current_section = clean_name
                skipped_rows.append((sheet_name, row_num, skip_reason))
                continue
            if skip_reason is not None:
                skipped_rows.append((sheet_name, row_num, skip_reason))
                continue

            parsed = parse_row(
                row_index=seq_idx,
                source_row=row_num,
                raw_text=combined_text_for_flags or clean_name,
                raw_code=raw_code,
                raw_price=None,
            )

            padded_cells = list(vals) + [None] * max(0, max_len - len(vals))

            items.append(
                OrderItem(
                    sheet_name=sheet_name,
                    source_row=row_num,
                    raw_text=clean_name,
                    raw_code=clean_code,
                    raw_qty=raw_qty,
                    raw_unit=raw_unit,
                    raw_note=raw_note or (" ; ".join(extra_parts) if extra_parts else None),
                    norm_text=parsed.norm_text,
                    qty=clean_q,
                    section_name=current_section,
                    codes=parsed.codes,
                    exclusion_flags=parsed.exclusion_flags,
                    direction_flags=parsed.direction_flags,
                    note_flags=parsed.note_flags,
                    warnings=parsed.warnings,
                    headers=headers,
                    raw_cells=padded_cells[:max_len],
                )
            )

    return OrderLoadResult(
        items=items,
        sheets_processed=sheets_processed,
        skipped_rows=skipped_rows,
    )