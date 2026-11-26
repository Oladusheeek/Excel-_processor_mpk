from __future__ import annotations

import math
import re
from typing import Any

# Визуально одинаковые буквы (гомоглифы) приводятся к единому алфавиту для сопоставления ключей
_HOMOGLYPHS = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "а": "a",
        "в": "b",
        "с": "c",
        "е": "e",
        "к": "k",
        "м": "m",
        "о": "o",
        "р": "p",
        "т": "t",
        "х": "x",
        "Ё": "E",
        "ё": "e",
    }
)

_EMPTY_STRINGS = {"", "-", "—", "–", "н/д", "нет", "none", "null", "nan"}
_JUNK_CHARS_RE = re.compile(r"[\u00a0\ufeff█■□]+")
_MULTI_SPACE_RE = re.compile(r"\s+")
_KEY_SEPARATORS_RE = re.compile(r"[\s\-._/]+")


def clean_optional_str(value: Any) -> str | None:
    """Приводит значение ячейки к очищенной строке или возвращает None для пустых/заглушечных значений."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None

    text = _JUNK_CHARS_RE.sub(" ", str(value))
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    if not text or text.lower() in _EMPTY_STRINGS:
        return None
    return text


def normalize_text(value: Any, *, lower: bool = True) -> str:
    """Нормализует текст для поиска и сравнения наименований."""
    cleaned = clean_optional_str(value)
    if not cleaned:
        return ""
    cleaned = cleaned.replace("ё", "е").replace("Ё", "Е")
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip()
    return cleaned.lower() if lower else cleaned


def canonical_code_key(code: Any) -> str:
    """
    Формирует каноничный ключ каталожного кода для сопоставления:
    - приводит к верхнему регистру;
    - унифицирует визуально одинаковые символы (гомоглифы);
    - убирает разделители (пробелы, дефисы, точки, подчёркивания, слэши).
    """
    cleaned = clean_optional_str(code)
    if not cleaned:
        return ""
    upper_mapped = cleaned.upper().translate(_HOMOGLYPHS)
    return _KEY_SEPARATORS_RE.sub("", upper_mapped)


def normalize_code_token(code: Any) -> str:
    """Совместимый алиас для получения нормализованного ключа кода."""
    return canonical_code_key(code)


def clean_number(value: Any) -> float | int | None:
    """
    Преобразует число или строку с числом (включая пробелы, запятые и 'шт.')
    в int или аккуратно округлённый float. Возвращает None, если число распознать нельзя.
    """
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        if abs(value - round(value)) < 1e-9:
            return int(round(value))
        return round(value, 6)

    cleaned = clean_optional_str(value)
    if not cleaned:
        return None

    # Убираем частые текстовые хвосты единиц измерения, если число записано в одной ячейке
    num_str = re.sub(r"(?i)\b(шт\.?|штук|компл\.?|комплект|кг|г|л|м)\b", "", cleaned)
    num_str = num_str.replace("\u00a0", " ").replace(" ", "").replace(",", ".")
    num_str = re.sub(r"[^0-9.+\-]", "", num_str)

    if not num_str or num_str in {"+", "-", ".", "-.", "+."}:
        return None

    try:
        parsed = float(num_str)
    except ValueError:
        return None

    if math.isnan(parsed) or math.isinf(parsed):
        return None
    if abs(parsed - round(parsed)) < 1e-9:
        return int(round(parsed))
    return round(parsed, 6)