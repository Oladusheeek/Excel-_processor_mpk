from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MatcherSettings:
    """Настройки движка сопоставления и цветового оформления отчёта."""

    # Пороги нечёткого поиска (0..100, для rapidfuzz)
    fuzzy_code_min_score: float = 82.0
    fuzzy_name_min_score: float = 75.0
    fuzzy_strong_score: float = 90.0
    max_fuzzy_candidates: int = 3

    # Поведение при дублях и расхождениях
    sum_duplicate_stock_by_default: bool = False
    treat_zero_price_as_unconfirmed: bool = True

    # Цвета заливки строк/ячеек в итоговом Excel (без '#' для openpyxl PatternFill)
    status_colors: dict[str, str] = field(
        default_factory=lambda: {
            "ok": "E2EFDA",           # мягкий зелёный — всё подтверждено и доступно
            "warning": "FFF2CC",      # мягкий жёлтый — нужно уточнить/проверить детали
            "attention": "FCE4D6",    # мягкий оранжевый — конфликт/ограничение/нет остатка/заготовка
            "not_found": "FADBD8",    # мягкий красный — совпадение не найдено
        }
    )


DEFAULT_SETTINGS = MatcherSettings()