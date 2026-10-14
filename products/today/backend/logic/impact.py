import math
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from posthog.dataclasses import frozen

from ..facade import contracts
from ..facade.enums import ImpactNumberKey
from .evidence import signal_view
from .signal_text import RECORDING_SOURCES, SignalInput, js_number, text_of

_MIN_TICKETS = 2
_WEEKS_FROM_DAYS = 14
_MS_PER_HOUR = 3_600_000
_SECONDS_PER_DAY = 86_400
_TIME_LEAD = "takes "
_TIME_TAIL = "ms on average"
_CALLS_TAIL = " calls in last 24h"
_TIME_CHARS = frozenset("0123456789.,")
_CALLS_CHARS = frozenset("0123456789,")
_TICKET_TYPE = "ticket"
_QUERY_HOURS_SENTENCE = "database time a day, worked out from the query’s pganalyze stats."


@frozen
class _Occurrences:
    count: int
    oldest: datetime
    newest: datetime


@frozen
class _QueryCost:
    signal: SignalInput
    average_ms: str
    calls_per_day: str
    hours: float


@frozen
class _Occurrence:
    kind: str
    key: str


def _occurrence_of(signal: SignalInput) -> _Occurrence | None:
    if signal.source_product in RECORDING_SOURCES:
        session = text_of(signal.extra.get("session_id"))
        return _Occurrence(kind="sessions", key=session) if session else None
    if signal.source_type == _TICKET_TYPE:
        ticket = js_number(signal.extra.get("ticket_number")) or signal.source_id
        return _Occurrence(kind="tickets", key=f"{signal.source_product}:{ticket}") if ticket else None
    if signal.source_product == "analytics" and signal.source_type == "anomaly_investigation":
        return _Occurrence(kind="alerts", key=text_of(signal.extra.get("alert_check_id")) or signal.source_id)
    return None


def _is_ticket(signal: SignalInput) -> bool:
    occurrence = _occurrence_of(signal)
    return occurrence is not None and occurrence.kind == "tickets"


def _occurrences_by_kind(signals: list[SignalInput]) -> dict[str, _Occurrences]:
    first_seen: dict[str, dict[str, datetime]] = {}
    for signal in signals:
        occurrence = _occurrence_of(signal)
        if occurrence is None:
            continue
        times = first_seen.setdefault(occurrence.kind, {})
        times[occurrence.key] = min(signal.timestamp, times.get(occurrence.key, signal.timestamp))
    return {
        kind: _Occurrences(count=len(times), oldest=min(times.values()), newest=max(times.values()))
        for kind, times in first_seen.items()
    }


def last_occurrence(signals: list[SignalInput]) -> datetime | None:
    occurrences = [signal.timestamp for signal in signals if _occurrence_of(signal) is not None]
    return max(occurrences) if occurrences else None


def _amount(text: str) -> float:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return math.nan


def _grouped(value: float, max_fraction_digits: int) -> str:
    rounded = Decimal(repr(value)).quantize(Decimal(1).scaleb(-max_fraction_digits), rounding=ROUND_HALF_UP)
    text = f"{rounded:,f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _fixed(value: float, digits: int) -> str:
    return str(Decimal(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def _average_ms(content: str) -> str | None:
    lowered = content.lower()
    index = lowered.find(_TIME_LEAD)
    while index >= 0:
        start = index + len(_TIME_LEAD)
        end = start
        while end < len(content) and content[end] in _TIME_CHARS:
            end += 1
        tail = end
        while tail < len(content) and content[tail].isspace():
            tail += 1
        if end > start and lowered.startswith(_TIME_TAIL, tail):
            return content[start:end]
        index = lowered.find(_TIME_LEAD, index + 1)
    return None


def _calls_per_day(content: str) -> str | None:
    lowered = content.lower()
    index = lowered.find(_CALLS_TAIL)
    while index >= 0:
        start = index
        while start > 0 and content[start - 1] in _CALLS_CHARS:
            start -= 1
        if start < index:
            return content[start:index]
        index = lowered.find(_CALLS_TAIL, index + 1)
    return None


def _query_cost(signals: list[SignalInput]) -> _QueryCost | None:
    for signal in signals:
        time = _average_ms(signal.content) if signal.source_product == "pganalyze" else None
        calls = _calls_per_day(signal.content)
        if not time or not calls:
            continue
        count = _amount(calls)
        hours = _amount(time) * count / _MS_PER_HOUR
        if math.isfinite(hours) and hours > 0:
            return _QueryCost(signal=signal, average_ms=time, calls_per_day=_grouped(count, 0), hours=hours)
    return None


def _occurrence_span(occurrences: _Occurrences) -> str:
    days = max(1, int((occurrences.newest - occurrences.oldest).total_seconds() // _SECONDS_PER_DAY) + 1)
    if days >= _WEEKS_FROM_DAYS:
        return f"over {round(days / 7)} weeks"
    return f"over {days} days" if days > 1 else "in one day"


def _ticket_number(signals: list[SignalInput]) -> contracts.ImpactNumber | None:
    tickets = _occurrences_by_kind(signals).get("tickets")
    if tickets is None or tickets.count < _MIN_TICKETS:
        return None
    ticket = next((signal for signal in signals if _is_ticket(signal)), None)
    return contracts.ImpactNumber(
        key=ImpactNumberKey.TICKETS,
        value=str(tickets.count),
        sentence=f"support tickets {_occurrence_span(tickets)}.",
        signal=signal_view(ticket) if ticket else None,
        values=[],
        working=None,
    )


def _query_hours_number(signals: list[SignalInput]) -> contracts.ImpactNumber | None:
    cost = _query_cost(signals)
    if cost is None:
        return None
    hours = _grouped(cost.hours, 1 if cost.hours < 10 else 0)
    return contracts.ImpactNumber(
        key=ImpactNumberKey.QUERY_HOURS,
        value=f"{hours} {'hour' if hours == '1' else 'hours'}",
        sentence=_QUERY_HOURS_SENTENCE,
        signal=signal_view(cost.signal),
        values=[cost.average_ms, cost.calls_per_day],
        working=contracts.ImpactWorking(
            expression=f"{cost.average_ms} ms × {cost.calls_per_day} calls",
            result=f"{_fixed(cost.hours, 2)} hours a day",
        ),
    )


def impact_numbers(signals: list[SignalInput]) -> list[contracts.ImpactNumber]:
    return [number for number in (_ticket_number(signals), _query_hours_number(signals)) if number is not None]
