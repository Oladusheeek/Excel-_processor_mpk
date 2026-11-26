from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from loaders.stock_loader import load_stock


def run_stock_check(
    stock_path: str = "СКЛАД МПК 01.11.26.xlsx",
    target_date: str | None = None,
    out_path: str = "stock_loaded_preview.xlsx",
) -> None:
    res = load_stock(stock_path, target_date=target_date, include_tooling=False)

    rows_out = []
    for it in res.items:
        rows_out.append({
            "sheet_name": it.sheet_name,
            "source_row": it.source_row,
            "section_name": it.section_name or "—",
            "raw_code": it.raw_code or "—",
            "raw_text": it.raw_text or "—",
            "qty": it.qty,
            "codes": "; ".join(f"{c.display} (key={c.normalized}, alt={c.is_alternative})" for c in it.codes) or "—",
            "exclusions": ", ".join(it.exclusion_flags) or "—",
            "directions": ", ".join(it.direction_flags) or "—",
            "warnings": ", ".join(it.warnings) or "—",
        })

    df_out = pd.DataFrame(rows_out)
    df_out.to_excel(out_path, index=False)

    print(f"Листов склада обработано: {res.sheets_processed}")
    print(f"Пропущено листов: {res.skipped_sheets}")
    print(f"Выбранные колонки остатков: {res.selected_date_columns}")
    print(f"Товарных позиций загружено: {len(df_out)}")
    if not df_out.empty:
        print("Позиций с ненулевым остатком:", int((df_out["qty"].fillna(0) > 0).sum()))
        print("Позиций с признаками исключений (литье/поковка/заготовка...):", int((df_out["exclusions"] != "—").sum()))
    print(f"Результат сохранён в: {out_path}")


if __name__ == "__main__":
    run_stock_check()