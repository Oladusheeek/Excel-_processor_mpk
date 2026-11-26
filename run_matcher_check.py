from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from core.matcher import match_order
from loaders.order_loader import load_order
from loaders.price_loader import load_price_list
from loaders.stock_loader import load_stock


def run_matcher_check(
    order_path: str = "заявка.xlsx",
    price_path: str = "price.xlsx",
    stock_path: str = "СКЛАД МПК 01.11.26.xlsx",
    target_date: str | None = None,
    out_path: str = "matched_preview.xlsx",
) -> None:
    order_res = load_order(order_path)
    price_res = load_price_list(price_path)
    stock_res = load_stock(stock_path, target_date=target_date, include_tooling=False)

    results = match_order(
        order_res.items,
        price_items=price_res.items,
        stock_items=stock_res.items,
    )

    rows_out = []
    for r in results:
        oi = r.order_item
        rows_out.append({
            "order_row": oi.source_row,
            "raw_code": oi.raw_code or "—",
            "raw_text": oi.raw_text or "—",
            "order_qty": oi.qty,
            "unit": oi.raw_unit or "—",
            "price": r.price,
            "stock_qty": r.stock_qty,
            "price_row": r.price_row,
            "stock_row": r.stock_row,
            "status": r.status.value,
            "comment": r.comment,
        })

    df_out = pd.DataFrame(rows_out)
    df_out.to_excel(out_path, index=False)

    print(f"Позиций проверено: {len(df_out)}")
    if not df_out.empty:
        print("Статусы:", df_out["status"].value_counts().to_dict())
        print("С ценой из прайса:", int(df_out["price"].notna().sum()))
        print("С остатком со склада:", int(df_out["stock_qty"].notna().sum()))
    print(f"Результат сохранён в: {out_path}")


if __name__ == "__main__":
    run_matcher_check()