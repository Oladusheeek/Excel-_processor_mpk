from __future__ import annotations

import re

# Пары взаимоисключающих характеристик (антонимов)
ANTONYM_PAIRS: list[tuple[str, str]] = [
    ("верхний", "нижний"),
    ("левый", "правый"),
    ("передний", "задний"),
]

# Признаки неготовых изделий / заготовок / оснастки (исключаются из готового остатка по умолчанию)
EXCLUSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "литье": ("литье", "литьё", "отливка"),
    "поковка": ("поковка", "поковки", "кованый", "кованая"),
    "заготовка": ("заготовка", "заготовки"),
    "полуфабрикат": ("полуфабрикат", "полуфабрикаты"),
    "оснастка": ("оснастка", "оснастки", "пресс-форма", "штамп", "модельный"),
}

# Примечания и ограничения в наименованиях/заявках
NOTE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "только_для_сборки": ("только для сборки",),
    "в_сборе": ("в сборе", "в сб.", "в сб"),
    "каленная": ("каленная", "калённая", "закаленная", "закалённая"),
    "агросеть": ("агросеть",),
}


def find_conflicting_directions(
    order_directions: list[str] | set[str],
    ref_directions: list[str] | set[str],
) -> list[tuple[str, str]]:
    """
    Возвращает список конфликтующих пар характеристик между заявкой и справочником,
    например [('нижний', 'верхний')].
    """
    ord_set = {d.strip().lower() for d in order_directions if d}
    ref_set = {d.strip().lower() for d in ref_directions if d}
    conflicts: list[tuple[str, str]] = []

    for a, b in ANTONYM_PAIRS:
        if a in ord_set and b in ref_set:
            conflicts.append((a, b))
        if b in ord_set and a in ref_set:
            conflicts.append((b, a))

    return conflicts


def contains_any_phrase(text: str | None, phrases: tuple[str, ...]) -> bool:
    if not text:
        return False
    low = re.sub(r"\s+", " ", text.lower()).strip()
    return any(p in low for p in phrases)