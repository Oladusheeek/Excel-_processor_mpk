from __future__ import annotations

from enum import Enum


class RowStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ATTENTION = "attention"
    NOT_FOUND = "not_found"


class CommentTemplates:
    """Шаблоны комментариев и статусов проверки по позициям заявки."""

    NO_PRICE_MATCH = "Совпадение в прайсе не подтверждено."
    NO_STOCK_MATCH = "Остаток не подтверждён."
    ZERO_STOCK = "Остаток на складе: 0."
    ONLY_FOR_ASSEMBLY = "В заявке указано ограничение на продажу (ТОЛЬКО ДЛЯ СБОРКИ)."

    ZERO_OR_MISSING_PRICE = "В прайсе цена не указана или равна 0 — уточнить."
    MADE_TO_ORDER_SHEET = "Позиция из раздела «Изготовление на заказ» (цена в прайсе отсутствует)."
    NOVELTY_SHEET = "Позиция из раздела «НОВИНКИ»."

    SUFFIX_MISMATCH_PRICE = "В прайсе найден код с другим суффиксом: {code} (стр. {row})."
    SUFFIX_MISMATCH_STOCK = "В остатках найден код с другим суффиксом: {code} (стр. {row})."

    DIRECTION_CONFLICT_PRICE = "Конфликт характеристик в прайсе (заявка: {ord_dir}, прайс: {ref_dir}, стр. {row})."
    DIRECTION_CONFLICT_STOCK = "В остатках по этому коду указан {ref_dir} элемент, в заявке {ord_dir} (стр. {row})."

    EXCLUDED_STOCK_ITEM = "{kind_title} в остатках (стр. {row}) исключена из готового остатка."
    EXCLUDED_PRICE_ITEM = "{kind_title} в прайсе (стр. {row}) — проверить исполнение."

    DUPLICATE_STOCK_ROWS = "Несколько записей остатков по артикулу (стр. {rows}). Уточнить исполнение перед суммированием."
    DUPLICATE_PRICE_SAME_PRICE = "Одинаковая цена по нескольким записям/артикулам (прайс, стр. {rows})."
    DUPLICATE_PRICE_DIFF_PRICE = "Несколько записей в прайсе по артикулу с разными ценами (стр. {rows})."

    FUZZY_CANDIDATES_PRICE = "Похожие позиции в прайсе: {candidates}."
    FUZZY_CANDIDATES_STOCK = "Похожие позиции на складе: {candidates}."
    FUZZY_CANDIDATES = "Похожие позиции: {candidates}."
    PROD_PLAN_INFO = "Плановый выпуск: {qty} {unit} (стр. {row})."