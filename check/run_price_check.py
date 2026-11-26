from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from loaders.price_loader import load_price_list


def run_price_check(
    price_path: str = "price.xlsx",
    out_path: str = "price_loaded_preview.xlsx",
) -> None:
    res = load_price_list(price_path)

    rows_out = []
    for it in res.items:
        rows_out.append({
            "sheet_name": it.sheet_name,
            "source_row": it.source_row,
            "section_name": it.section_name or "—",
            "raw_code": it.raw_code or "—",
            "raw_text": it.raw_text or "—",
            "price": it.price if it.has_price_column else "нет колонки цены",
            "zero_or_missing_price": it.is_zero_or_missing_price,
            "is_novelty": it.is_novelty,
            "is_made_to_order": it.is_made_to_order,
            "codes": "; ".join(f"{c.display} (key={c.normalized}, alt={c.is_alternative})" for c in it.codes) or "—",
            "exclusions": ", ".join(it.exclusion_flags) or "—",
            "directions": ", ".join(it.direction_flags) or "—",
            "warnings": ", ".join(it.warnings) or "—",
        })

    df_out = pd.DataFrame(rows_out)
    df_out.to_excel(out_path, index=False)

    print(f"Листов обработано: {res.sheets_processed}")
    print(f"Позиций загружено: {len(df_out)}, пропущено служебных строк: {len(res.skipped_rows)}")
    if not df_out.empty:
        print("По листам:", df_out["sheet_name"].value_counts().to_dict())
        print("Нулевая/пустая цена (основной прайс/новинки):", int(df_out["zero_or_missing_price"].sum()))
    print(f"Результат сохранён в: {out_path}")


if __name__ == "__main__":
    run_price_check()