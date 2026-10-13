import datetime as dt
import dataclasses


@dataclasses.dataclass(frozen=True)
class ScanRow:
    date: dt.date
    org_id: str
    team_id: int
    query_source: str
    logical_bytes_scanned: int


@dataclasses.dataclass(frozen=True)
class ParsedScanRows:
    rows: list[ScanRow] = dataclasses.field(default_factory=list)
    unparsed: list[object] = dataclasses.field(default_factory=list)
    invalid: list[object] = dataclasses.field(default_factory=list)
    invalid_scopes: frozenset[tuple[str, dt.date, str]] = dataclasses.field(default_factory=frozenset)
    malformed: bool = False


def parse_scan_rows(raw_scans: object) -> ParsedScanRows:
    if not isinstance(raw_scans, list):
        return ParsedScanRows(malformed=True)
    rows: list[ScanRow] = []
    unparsed: list[object] = []
    invalid: list[object] = []
    invalid_scopes: set[tuple[str, dt.date, str]] = set()
    for raw in raw_scans:
        try:
            if not isinstance(raw, dict):
                raise TypeError("expected a scan row object")
            value = raw["logical_bytes_scanned"]
            # Floats and booleans cannot represent an exact received integer counter.
            if type(value) is not int or abs(value) >= 10**38:
                raise ValueError("logical_bytes_scanned must be a JSON integer with at most 38 digits")
            if not isinstance(raw["org_id"], str) or not isinstance(raw["query_source"], str):
                raise TypeError("expected string identity and source fields")
            if type(raw["team_id"]) is not int or not 0 <= raw["team_id"] < 2**63:
                raise ValueError("team_id must be a nonnegative JSON int64")
            if len(raw["query_source"]) > 32:
                raise ValueError("query_source exceeds mirror field width")
            row = ScanRow(
                date=dt.date.fromisoformat(raw["date"]),
                org_id=raw["org_id"],
                team_id=raw["team_id"],
                query_source=raw["query_source"],
                logical_bytes_scanned=value,
            )
        except (KeyError, ValueError, TypeError, OverflowError):
            unparsed.append(raw)
            continue
        if value < 0:
            invalid.append(raw)
            invalid_scopes.add((row.org_id, row.date, row.query_source))
            continue
        rows.append(row)
    return ParsedScanRows(rows=rows, unparsed=unparsed, invalid=invalid, invalid_scopes=frozenset(invalid_scopes))
