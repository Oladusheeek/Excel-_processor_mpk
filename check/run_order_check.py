from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from loaders.order_loader import load_order


def run_order_check(
    order_path: str = "ГСМ 2027 заявка.xlsx",
    out_path: str = "order_loaded_preview.xlsx",
) -> None:
    res = load_order(order_path)

    rows_out = []
    for it in res.items:
        rows_out.append({
            "sheet_name": it.sheet_name,
            "source_row": it.source_row,
            "section_name": it.section_name or "—",
            "raw_code": it.raw_code or "—",
            "raw_text": it.raw_text or "—",
            "raw_qty": it.raw_qty,
            "clean_qty": it.qty,
            "unit": it.raw_unit or "—",
            "note": it.raw_note or "—",
            "codes": "; ".join(f"{c.display} (key={c.normalized}, alt={c.is_alternative})" for c in it.codes) or "—",
            "note_flags": ", ".join(it.note_flags) or "—",
            "directions": ", ".join(it.direction_flags) or "—",
            "exclusions": ", ".join(it.exclusion_flags) or "—",
            "warnings": ", ".join(it.warnings) or "—",
        })

    df_out = pd.DataFrame(rows_out)
    df_out.to_excel(out_path, index=False)

    print(f"Листов обработано: {res.sheets_processed}")
    print(f"Позиций заявки загружено: {len(df_out)}, пропущено служебных строк: {len(res.skipped_rows)}")
    if not df_out.empty:
        print("Строк без извлечённого кода:", int((df_out["codes"] == "—").sum()))
        print("Строк с флагами примечаний (напр. ТОЛЬКО ДЛЯ СБОРКИ):", int((df_out["note_flags"] != "—").sum()))
    print(f"Результат сохранён в: {out_path}")


if __name__ == "__main__":
    run_order_check()