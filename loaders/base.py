from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl

from core.normalizer import clean_optional_str
from core.parser import ParsedCode, parse_row


@dataclass
class ReferenceItem:
    """Унифицированная позиция справочника (прайс, склад, план производства)."""

    source_type: str  # "price" | "stock" | "prod_plan"
    sheet_name: str
    source_row: int
    raw_text: str | None
    raw_code: str | None
    norm_text: str
    section_name: str | None = None
    price: float | int | None = None
    qty: float | int | None = None
    has_price_column: bool = True
    is_zero_or_missing_price: bool = False
    is_made_to_order: bool = False
    is_novelty: bool = False
    codes: list[ParsedCode] = field(default_factory=list)
    exclusion_flags: list[str] = field(default_factory=list)
    direction_flags: list[str] = field(default_factory=list)
    note_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_code_keys(self) -> list[str]:
        return [c.normalized for c in self.codes]

    @property
    def all_base_keys(self) -> list[str]:
        return [c.base for c in self.codes if c.base]


def load_workbook_sheets(file_path: str | Path) -> dict[str, list[tuple[int, list[Any]]]]:
    """
    Читает все листы .xlsx через openpyxl (data_only=True) с сохранением реальных номеров строк.
    Возвращает словарь: {sheet_name: [(excel_row_num, [cell_values...]), ...]}.
    """
    path = Path(file_path)
    wb = openpyxl.load_workbook(path, data_only=True)
    result: dict[str, list[tuple[int, list[Any]]]] = {}

    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows: list[tuple[int, list[Any]]] = []
            for row_idx in range(1, ws.max_row + 1):
                values = [ws.cell(row_idx, col_idx).value for col_idx in range(1, ws.max_column + 1)]
                if any(clean_optional_str(v) is not None or isinstance(v, (int, float)) for v in values):
                    rows.append((row_idx, values))
            result[sheet_name] = rows
    finally:
        wb.close()

    return result


def build_reference_item_from_parsed(
    *,
    source_type: str,
    sheet_name: str,
    source_row: int,
    row_index: int,
    raw_text: Any,
    raw_code: Any = None,
    raw_price: Any = None,
    raw_qty: Any = None,
    section_name: str | None = None,
    has_price_column: bool = True,
    is_made_to_order: bool = False,
    is_novelty: bool = False,
) -> ReferenceItem:
    """Преобразует сырую строку таблицы в ReferenceItem с использованием core.parser."""
    from core.normalizer import clean_number

    parsed = parse_row(
        row_index=row_index,
        source_row=source_row,
        raw_text=raw_text,
        raw_code=raw_code,
        raw_price=raw_price,
    )
    clean_qty = clean_number(raw_qty) if raw_qty is not None else None
    zero_or_missing = (
        False
        if is_made_to_order or not has_price_column
        else (parsed.clean_price is None or parsed.clean_price == 0)
    )

    return ReferenceItem(
        source_type=source_type,
        sheet_name=sheet_name,
        source_row=source_row,
        raw_text=parsed.raw_text,
        raw_code=parsed.raw_code,
        norm_text=parsed.norm_text,
        section_name=section_name,
        price=parsed.clean_price if has_price_column else None,
        qty=clean_qty,
        has_price_column=has_price_column,
        is_zero_or_missing_price=zero_or_missing,
        is_made_to_order=is_made_to_order,
        is_novelty=is_novelty,
        codes=parsed.codes,
        exclusion_flags=parsed.exclusion_flags,
        direction_flags=parsed.direction_flags,
        note_flags=parsed.note_flags,
        warnings=parsed.warnings,
    )