import re
import math
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from posthog.dataclasses import frozen

from ..facade import contracts
from .signal_text import SignalInput, headline, js_number, text_of

_MIN_TICKETS = 2
_WEEKS_FROM_DAYS = 14
_MS_PER_HOUR = 3_600_000
_SECONDS_PER_DAY = 86_400
_PGANALYZE_TIME = re.compile(r"takes ([\d.,]+)\s*ms on average", re.IGNORECASE | re.ASCII)
_PGANALYZE_CALLS = re.compile(r"([\d,]+) calls in last 24h", re.IGNORECASE | re.ASCII)
_RECORDING_SOURCES = frozenset({"replay_vision", "session_replay"})
_TICKET_SOURCES = frozenset({"conversations", "zendesk"})
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


def _occurrence_of(signal: SignalInput) -> tuple[str, str] | None:
    if signal.source_product in _RECORDING_SOURCES:
        session = text_of(signal.extra.get("session_id"))
        return ("sessions", session) if session else None
    if signal.source_product in _TICKET_SOURCES:
        ticket = js_number(signal.extra.get("ticket_number")) or signal.source_id
        return ("tickets", ticket) if ticket else None
    if signal.source_product == "analytics" and signal.source_type == "anomaly_investigation":
        return ("alerts", text_of(signal.extra.get("alert_check_id")) or signal.source_id)
    return None


def _occurrences_by_kind(signals: list[SignalInput]) -> dict[str, _Occurrences]:
    first_seen: dict[str, dict[str, datetime]] = {}
    for signal in signals:
        occurrence = _occurrence_of(signal)
        if occurrence is None:
            continue
        kind, key = occurrence
        times = first_seen.setdefault(kind, {})
        times[key] = min(signal.timestamp, times.get(key, signal.timestamp))
    return {
        kind: _Occurrences(count=len(times), oldest=min(times.values()), newest=max(times.values()))
        for kind, times in first_seen.items()
    }


def last_occurrence(signals: list[SignalInput]) -> datetime | None:
    newest = [occurrences.newest for occurrences in _occurrences_by_kind(signals).values()]
    return max(newest) if newest else None


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


def _query_cost(signals: list[SignalInput]) -> _QueryCost | None:
    for signal in signals:
        time = _PGANALYZE_TIME.search(signal.content) if signal.source_product == "pganalyze" else None
        calls = _PGANALYZE_CALLS.search(signal.content)
        if not time or not calls:
            continue
        count = _amount(calls.group(1))
        hours = _amount(time.group(1)) * count / _MS_PER_HOUR
        if math.isfinite(hours) and hours > 0:
            return _QueryCost(signal=signal, average_ms=time.group(1), calls_per_day=_grouped(count, 0), hours=hours)
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
    ticket = next((signal for signal in signals if (_occurrence_of(signal) or ("", ""))[0] == "tickets"), None)
    return contracts.ImpactNumber(
        key="tickets",
        value=str(tickets.count),
        sentence=f"support tickets {_occurrence_span(tickets)}.",
        signal_id=ticket.signal_id if ticket else None,
        excerpt=headline(ticket) if ticket else "",
        values=[],
        working=None,
    )


def _query_hours_number(signals: list[SignalInput]) -> contracts.ImpactNumber | None:
    cost = _query_cost(signals)
    if cost is None:
        return None
    hours = _grouped(cost.hours, 1 if cost.hours < 10 else 0)
    return contracts.ImpactNumber(
        key="query-hours",
        value=f"{hours} {'hour' if hours == '1' else 'hours'}",
        sentence=_QUERY_HOURS_SENTENCE,
        signal_id=cost.signal.signal_id,
        excerpt=headline(cost.signal),
        values=[cost.average_ms, cost.calls_per_day],
        working=contracts.ImpactWorking(
            expression=f"{cost.average_ms} ms × {cost.calls_per_day} calls",
            result=f"{_fixed(cost.hours, 2)} hours a day",
        ),
    )


def impact_numbers(signals: list[SignalInput]) -> list[contracts.ImpactNumber]:
    return [number for number in (_ticket_number(signals), _query_hours_number(signals)) if number is not None]
