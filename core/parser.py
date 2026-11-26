from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.normalizer import clean_number, clean_optional_str, normalize_code_token, normalize_text

# Каталожные коды:
# 1) Коды с точками (от 1 точки и выше) и опциональными составными частями через дефис:
#    например 10.01.50.400, ЖЗЛ-04.002, 02601.09, Н023.204, Р 232.10.000,
#    90.140-01, ПУН 10.014, ИНК 10.59, ПУН 00.460, РМПК-2.127.1-3.4.000
_DOTTED_CODE_RE = re.compile(
    r"(?<![A-Za-zА-Яа-я0-9_.])"
    r"(?:(?:РСМ|КЗК|КЗР|РМПК|ЖЗЛ|УЛИГ|КУЖ|ПУН|ИНК|ГЦ|Н|Р)[\s\-]*)?"
    r"[0-9А-ЯЁA-Z]{1,6}(?:\.[0-9А-ЯЁA-Z]{1,4}){1,4}"
    r"(?:-[0-9A-Za-zА-Яа-я]+(?:\.[0-9A-Za-zА-Яа-я]+)*)*"
    r"(?![0-9A-Za-zА-Яа-я.])",
    re.IGNORECASE,
)

# 2) Коды с дефисами / префиксами:
#    например КЗК-12-0202900, 10-0290608, 10-0290608А, 3518050-18310, 54-0-47-2А
_DASHED_CODE_RE = re.compile(
    r"(?<![A-Za-zА-Яа-я0-9_.])"
    r"(?:(?:КЗК|КЗР|РСМ|РМПК|ЖЗЛ|УЛИГ|КУЖ|ПУН|ИНК)[\s\-]*)?"
    r"[0-9А-ЯЁA-Z]{1,8}(?:-[0-9A-Za-zА-Яа-я]{1,10}){1,4}"
    r"(?:[А-ЯЁA-Z]{1,2})?"
    r"(?![0-9A-Za-zА-Яа-я.])",
    re.IGNORECASE,
)
# 3) Префикс + пробел/дефис/слитно + числовой код (например «КЗК 0123000», «УЛИГ 2441200», «КУЖ 0122010», «К7006330»)
_PREFIXED_NUM_CODE_RE = re.compile(
    r"(?<![A-Za-zА-Яа-я0-9_.])"
    r"(?:КЗК|КЗР|РСМ|РМПК|ЖЗЛ|УЛИГ|КУЖ|ПУН|ИНК|ГЦ|К)[\s\-]*\d{5,8}[А-ЯЁA-Z]{0,2}"
    r"(?![0-9A-Za-zА-Яа-я.])",
    re.IGNORECASE,
)

# 4) Буквенно-цифровые коды/модели техники и цилиндров (например «ЦС50», «МТЗ80»)
_ALNUM_MODEL_CODE_RE = re.compile(
    r"(?<![A-Za-zА-Яа-я0-9_.])"
    r"(?:ЦС|МТЗ|ЮМЗ|Т|ДОН|АКРОС|ACROS|VECTOR|TORUM)\s*-?\d{2,4}[А-ЯЁA-Z0-9\-]*"
    r"(?![0-9A-Za-zА-Яа-я.])",
    re.IGNORECASE,
)

# Числительные с падежными окончаниями вроде «2-х», «3-х», «4-го» (не считать кодом)
_ORDINAL_NUM_RE = re.compile(r"^\d{1,3}-(?:х|го|я|е|и|ых|тых|ми)$", re.IGNORECASE)

# Суффикс модификации в конце кода: "-01", "-02", "А", "Б", "В", "Г" и т.п.
_SUFFIX_RE = re.compile(r"^(?P<base>.+?)(?P<suffix>(?:-\d{1,3}|[A-Z]{1,2}))$")

_EXCLUSION_PATTERNS: dict[str, re.Pattern[str]] = {
    "литье": re.compile(r"\bлить[её]\b", re.IGNORECASE),
    "поковка": re.compile(r"\bпоковк[аиуеой]?\b", re.IGNORECASE),
    "заготовка": re.compile(r"\bзаготовк[аиуеой]?\b", re.IGNORECASE),
    "полуфабрикат": re.compile(r"\bполуфабрикат[аыуеом]?\b", re.IGNORECASE),
    "оснастка": re.compile(r"\bоснастк[аиуеой]?\b", re.IGNORECASE),
}

_DIRECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "верхний": re.compile(r"\bверхн[ийяеюо][ймх]?\b", re.IGNORECASE),
    "нижний": re.compile(r"\bнижн[ийяеюо][ймх]?\b", re.IGNORECASE),
    "левый": re.compile(r"\bлев[аоыуеой][ймх]?\b", re.IGNORECASE),
    "правый": re.compile(r"\bправ[аоыуеой][ймх]?\b", re.IGNORECASE),
    "передний": re.compile(r"\bпередн[ийяеюо][ймх]?\b", re.IGNORECASE),
    "задний": re.compile(r"\bзадн[ийяеюо][ймх]?\b", re.IGNORECASE),
}

_NOTE_PATTERNS: dict[str, re.Pattern[str]] = {
    "только_для_сборки": re.compile(r"только\s+для\s+сборки", re.IGNORECASE),
    "в_сборе": re.compile(r"\bв\s+сб\.?\b|\bв\s+сборе\b", re.IGNORECASE),
    "каленная": re.compile(r"\bкаленн[аяоыеую][ймх]?\b", re.IGNORECASE),
    "агросеть": re.compile(r"\bагросеть\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class ParsedCode:
    raw: str
    display: str
    normalized: str
    base: str
    suffix: str | None
    source_field: str  # "raw_code" | "raw_text"
    is_alternative: bool = False


@dataclass
class ParsedRow:
    source_row: int | None
    row_index: int
    raw_text: str | None
    raw_code: str | None
    raw_price: Any
    norm_text: str
    norm_code_field: str | None
    clean_price: float | int | None
    codes: list[ParsedCode] = field(default_factory=list)
    exclusion_flags: list[str] = field(default_factory=list)
    direction_flags: list[str] = field(default_factory=list)
    note_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def format_display_code(code: str) -> str:
    """Приводит код к аккуратному отображаемому виду без смены алфавита префиксов."""
    token = normalize_text(code, lower=False).upper()
    token = token.strip("()[]{}.,;:/\\")
    token = re.sub(r"\s*-\s*", "-", token)
    token = re.sub(r"\s*\.\s*", ".", token)
    token = re.sub(r"\s+", " ", token).strip()
    return token


def split_base_and_suffix(norm_code: str) -> tuple[str, str | None]:
    """Разделяет нормализованный артикул на базовый код и суффикс модификации."""
    match = _SUFFIX_RE.match(norm_code)
    if not match:
        return norm_code, None
    base = match.group("base").rstrip("-.")
    suffix = match.group("suffix")
    if len(base) < 4 or not re.search(r"\d", base):
        return norm_code, None
    return base, suffix


def _prepare_text_for_code_scan(text: str) -> str:
    """Разделяет слипшиеся с буквами/скобками коды."""
    out = re.sub(r"([А-ЯЁA-Zа-яёa-z])(?=\d{2,3}[.\-]\d)", r"\1 ", text)
    out = re.sub(r"\)(?=[А-ЯЁA-Zа-яёa-z0-9])", r") ", out)
    out = re.sub(r"(?<=[А-ЯЁA-Zа-яёa-z0-9])\(", r" (", out)
    return out


def extract_codes_from_string(
    text: str,
    *,
    source_field: str,
    allow_pure_digits: bool = False,
) -> list[ParsedCode]:
    """Извлекает каталожные коды из строки с сохранением порядка и признаков альтернативности."""
    prepared = _prepare_text_for_code_scan(text)
    parts = re.split(r"\s*/\s*", prepared)

    found: list[ParsedCode] = []
    seen_norm: set[str] = set()

    for part_idx, part in enumerate(parts):
        raw_hits: list[tuple[int, int, str, bool]] = []

        for regex in (_DOTTED_CODE_RE, _DASHED_CODE_RE, _PREFIXED_NUM_CODE_RE, _ALNUM_MODEL_CODE_RE):
            for m in regex.finditer(part):
                raw_match = m.group(0)
                if _ORDINAL_NUM_RE.match(raw_match.strip()):
                    continue
                start, end = m.span()
                left_slice = part[:start]
                in_parens = left_slice.count("(") > left_slice.count(")")
                is_alt = (part_idx > 0) or in_parens
                raw_hits.append((start, end, raw_match, is_alt))

        raw_hits.sort(key=lambda item: (item[0], -(item[1] - item[0])))

        non_overlapping: list[tuple[int, int, str, bool]] = []
        last_end = -1
        for start, end, raw_match, is_alt in raw_hits:
            if start < last_end:
                continue
            non_overlapping.append((start, end, raw_match, is_alt))
            last_end = end

        for _, _, raw_match, is_alt in non_overlapping:
            display = format_display_code(raw_match)
            norm = normalize_code_token(raw_match)
            if not norm or norm in seen_norm:
                continue
            if re.fullmatch(r"\d+", norm) and not allow_pure_digits:
                continue
            if not re.search(r"\d", norm):
                continue
            seen_norm.add(norm)
            base, suffix = split_base_and_suffix(norm)
            found.append(
                ParsedCode(
                    raw=raw_match.strip(),
                    display=display,
                    normalized=norm,
                    base=base,
                    suffix=suffix,
                    source_field=source_field,
                    is_alternative=is_alt,
                )
            )

    # Фолбэк для отдельного поля кода, если в нём записан чистый цифровой артикул (5-9 цифр)
    if not found and allow_pure_digits:
        stripped = part.strip() if parts else prepared.strip()
        if re.fullmatch(r"\d{5,9}", stripped):
            display = format_display_code(stripped)
            norm = normalize_code_token(stripped)
            base, suffix = split_base_and_suffix(norm)
            found.append(
                ParsedCode(
                    raw=stripped,
                    display=display,
                    normalized=norm,
                    base=base,
                    suffix=suffix,
                    source_field=source_field,
                    is_alternative=False,
                )
            )

    return found


def parse_row(
    *,
    row_index: int,
    source_row: Any = None,
    raw_text: Any = None,
    raw_code: Any = None,
    raw_price: Any = None,
) -> ParsedRow:
    """Разбирает строку входных данных в нормализованную структуру ParsedRow."""
    clean_source_row = clean_number(source_row)
    src_row_int = int(clean_source_row) if isinstance(clean_source_row, (int, float)) else None

    clean_text = clean_optional_str(raw_text)
    clean_code = clean_optional_str(raw_code)
    norm_text = normalize_text(clean_text, lower=True)
    norm_code_field = normalize_code_token(clean_code) if clean_code else None
    clean_price = clean_number(raw_price)

    warnings: list[str] = []
    if clean_text and clean_text.count("(") != clean_text.count(")"):
        warnings.append("unbalanced_parens_in_text")
    if clean_code and clean_code.count("(") != clean_code.count(")"):
        warnings.append("unbalanced_parens_in_code")

    codes: list[ParsedCode] = []
    seen_norm: set[str] = set()

    if clean_code:
        for item in extract_codes_from_string(
            clean_code,
            source_field="raw_code",
            allow_pure_digits=True,
        ):
            if item.normalized not in seen_norm:
                seen_norm.add(item.normalized)
                codes.append(item)

    if clean_text:
        for item in extract_codes_from_string(
            clean_text,
            source_field="raw_text",
            allow_pure_digits=False,
        ):
            if item.normalized not in seen_norm:
                seen_norm.add(item.normalized)
                codes.append(item)

    exclusion_flags = [
        name for name, pat in _EXCLUSION_PATTERNS.items() if clean_text and pat.search(clean_text)
    ]
    direction_flags = [
        name for name, pat in _DIRECTION_PATTERNS.items() if clean_text and pat.search(clean_text)
    ]
    note_flags = [
        name for name, pat in _NOTE_PATTERNS.items() if clean_text and pat.search(clean_text)
    ]

    return ParsedRow(
        source_row=src_row_int,
        row_index=row_index,
        raw_text=clean_text,
        raw_code=clean_code,
        raw_price=raw_price,
        norm_text=norm_text,
        norm_code_field=norm_code_field,
        clean_price=clean_price,
        codes=codes,
        exclusion_flags=exclusion_flags,
        direction_flags=direction_flags,
        note_flags=note_flags,
        warnings=warnings,
    )