from decimal import Decimal
from typing import Literal

from posthog.dataclasses import frozen

from .formats import digits_end, is_digit, is_word_char

_CURRENCIES = frozenset("$€£")
_BLOCKED_BEFORE = frozenset(".,-/:#$@→")
_BLOCKED_AFTER = frozenset(":/→")
_RANGE_DASHES = frozenset("–-")
_SCALES = {"K": Decimal(1_000), "M": Decimal(1_000_000)}
_UNIT_WORDS = ("ms", "K", "M")
_DURATION_UNITS = frozenset(
    {"second", "seconds", "minute", "minutes", "hour", "hours", "day", "days", "week", "weeks", "month", "months"}
)
_NOUN_QUOTES = frozenset("'\"‘“")

type AmountKind = Literal["percent", "milliseconds", "money", "count"]


@frozen
class Amount:
    kind: AmountKind
    low: Decimal
    high: Decimal
    upper: Decimal | None


@frozen
class Figure:
    start: int
    end: int
    text: str
    noun: str | None
    amount: Amount


@frozen
class _Token:
    upper: str | None
    unit: str | None
    end: int


def _number_end(text: str, start: int) -> int:
    end = digits_end(text, start)
    if end - start <= 3:
        while text.startswith(",", end) and digits_end(text, end + 1) - (end + 1) == 3:
            end = digits_end(text, end + 1)
    if text.startswith(".", end) and end + 1 < len(text) and is_digit(text[end + 1]):
        end = digits_end(text, end + 1)
    return end


def _after_space(text: str, index: int) -> int:
    return index + 1 if text.startswith(" ", index) else index


def _range_upper(text: str, index: int) -> tuple[str | None, int]:
    dash = _after_space(text, index)
    if dash >= len(text) or text[dash] not in _RANGE_DASHES:
        return None, index
    second = _after_space(text, dash + 1)
    if second >= len(text) or not is_digit(text[second]):
        return None, index
    end = _number_end(text, second)
    return text[second:end], end


def _unit(text: str, index: int) -> tuple[str | None, int]:
    if text.startswith("%", index):
        return "%", index + 1
    start = _after_space(text, index)
    for unit in _UNIT_WORDS:
        end = start + len(unit)
        if text.startswith(unit, start) and (end == len(text) or not is_word_char(text[end])):
            return unit, end
    return None, index


def _token(text: str, number_end: int) -> _Token:
    upper, range_end = _range_upper(text, number_end)
    unit, end = _unit(text, range_end)
    if upper is not None or unit not in _SCALES:
        return _Token(upper=upper, unit=unit, end=end)
    scaled_upper, scaled_range_end = _range_upper(text, end)
    if scaled_upper is None:
        return _Token(upper=None, unit=unit, end=end)
    upper_unit, upper_end = _unit(text, scaled_range_end)
    if upper_unit != unit:
        return _Token(upper=None, unit=unit, end=end)
    return _Token(upper=scaled_upper, unit=unit, end=upper_end)


def _free_after(text: str, end: int) -> bool:
    following = text[end] if end < len(text) else ""
    decimal_after = following in ".," and end + 1 < len(text) and is_digit(text[end + 1])
    return not is_word_char(following) and following not in _BLOCKED_AFTER and not decimal_after


def _noun_after(text: str, end: int) -> str | None:
    index = end
    while index < len(text) and text[index].isspace():
        index += 1
    if index == end:
        return None
    if index < len(text) and text[index] in _NOUN_QUOTES:
        index += 1
    start = index
    while (
        index < len(text)
        and text[index].isascii()
        and (text[index].isalpha() or (index > start and text[index] == "-"))
    ):
        index += 1
    return text[start:index] or None


def _duration_end(text: str, end: int, noun: str | None, bare: bool) -> int:
    if not bare or noun is None or noun.lower() not in _DURATION_UNITS:
        return end
    word_start = end
    while word_start < len(text) and text[word_start].isspace():
        word_start += 1
    return word_start + len(noun) if text.startswith(noun, word_start) else end


def _spread(value: str, unit: str | None) -> Decimal:
    scale = _SCALES.get(unit or "")
    if scale is None:
        return Decimal(0)
    decimals = len(value.split(".")[1]) if "." in value else 0
    return Decimal(5) * scale / Decimal(10) ** (decimals + 1)


def _kind(unit: str | None, currency: bool) -> AmountKind:
    if unit == "%":
        return "percent"
    if unit == "ms":
        return "milliseconds"
    return "money" if currency else "count"


def _amount(value: str, token: _Token, currency: bool) -> Amount:
    scale = _SCALES.get(token.unit or "", Decimal(1))
    center = Decimal(value.replace(",", "")) * scale
    spread = _spread(value, token.unit)
    return Amount(
        kind=_kind(token.unit, currency),
        low=center - spread,
        high=center + spread,
        upper=Decimal(token.upper.replace(",", "")) * scale if token.upper else None,
    )


def _number_start(text: str, index: int) -> tuple[int, bool] | None:
    currency = text[index] in _CURRENCIES
    digit_start = index + 1 if currency else index
    if digit_start >= len(text) or not is_digit(text[digit_start]):
        return None
    before = text[index - 1] if index > 0 else ""
    if is_word_char(before) or before in _BLOCKED_BEFORE:
        return None
    return digit_start, currency


def numbers_in(text: str) -> list[Figure]:
    figures: list[Figure] = []
    index = 0
    while index < len(text):
        start = _number_start(text, index)
        if start is None:
            index = digits_end(text, index) if is_digit(text[index]) else index + 1
            continue
        digit_start, currency = start
        number_end = _number_end(text, digit_start)
        value = text[digit_start:number_end]
        token = _token(text, number_end)
        if not _free_after(text, token.end):
            index = token.end
            continue
        noun = _noun_after(text, token.end)
        end = _duration_end(text, token.end, noun, bare=token.unit is None and not currency)
        figures.append(
            Figure(start=index, end=end, text=text[index:end], noun=noun, amount=_amount(value, token, currency))
        )
        index = end
    return figures


def is_zero(amount: Amount) -> bool:
    return amount.high == 0 and amount.upper is None


def same_amount(claim: Amount, source: Amount) -> bool:
    if claim.kind != source.kind or claim.upper != source.upper:
        return False
    return claim.low <= source.low and source.high <= claim.high
