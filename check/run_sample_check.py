from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from core.normalizer import clean_optional_str
from core.parser import parse_row


def run_check(xlsx_path: str = "test_data.xlsx", out_path: str = "sample_parsed_preview.xlsx") -> None:
    df = pd.read_excel(xlsx_path, sheet_name="Лист1")

    current_section = "Без раздела"
    parsed_records: list[dict] = []

    for idx, row in df.iterrows():
        c0 = clean_optional_str(row.iloc[0])
        c1 = clean_optional_str(row.iloc[1])
        c2 = clean_optional_str(row.iloc[2])
        c3 = row.iloc[3]

        # Заголовок секции в первой колонке (не число и остальные колонки пустые)
        if c0 and not c0.isdigit() and c1 is None and c2 is None:
            current_section = c0
            continue

        # Повторная строка заголовков внутри таблицы
        if c1 == "raw_text" and c2 == "raw_code":
            continue

        # Полностью пустая строка
        if c0 is None and c1 is None and c2 is None and pd.isna(c3):
            continue

        item = parse_row(
            row_index=idx + 2,
            source_row=row.iloc[0],
            raw_text=row.iloc[1],
            raw_code=row.iloc[2],
            raw_price=row.iloc[3],
        )

        codes_formatted = "; ".join(
            f"{c.display} (key={c.normalized}, base={c.base}, suf={c.suffix or '-'}, src={c.source_field}, alt={c.is_alternative})"
            for c in item.codes
        )

        parsed_records.append({
            "section": current_section,
            "excel_row": item.row_index,
            "source_row": item.source_row,
            "raw_text": item.raw_text,
            "raw_code": item.raw_code,
            "clean_price": item.clean_price,
            "extracted_codes": codes_formatted or "—",
            "exclusions": ", ".join(item.exclusion_flags) or "—",
            "directions": ", ".join(item.direction_flags) or "—",
            "notes": ", ".join(item.note_flags) or "—",
            "warnings": ", ".join(item.warnings) or "—",
        })

    result_df = pd.DataFrame(parsed_records)
    result_df.to_excel(out_path, index=False)
    print(f"Обработано строк: {len(result_df)}. Сохранено в: {out_path}\n")
    print(
        result_df[
            ["section", "source_row", "clean_price", "extracted_codes", "exclusions", "directions", "warnings"]
        ].to_string()
    )


if __name__ == "__main__":
    run_check()