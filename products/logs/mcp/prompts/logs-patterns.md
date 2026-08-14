Mine recurring log templates ("patterns") from the logs matching a filter set, ordered by frequency. Each pattern is a message template with the variable parts masked — e.g. `Connected to <ip> in <num>ms` — plus occurrence estimates, severity mix, the services it appears in, and a ready-made predicate for fetching its matching lines.

This is the fastest way to understand what a log stream is _saying_ without reading raw rows: one call summarizes millions of lines into at most 200 templates.

All parameters must be nested inside a `query` object.

# When to use

- To triage an unfamiliar or noisy stream: mine the last hour, scan the top templates by `estimated_count`, and look for anything with a non-zero error share in `severity_counts`.
- To find what's new or dominant during an incident window: mine with `severityLevels: ["error", "fatal"]` and a `dateRange` covering the incident.
- As the entry point of a drill-down loop: mine → pick a suspicious pattern → filter logs to exactly its lines using `match_regex` (see below) → read the raw rows with `query-logs`.
- To quantify repetition before proposing log sampling or cleanup: `volume_share_pct` tells you how much of the stream one template accounts for.

## Pick the right tool

- Raw log lines matching a filter → `query-logs`.
- A single number (how many logs match) → `logs-count`; per-time-bucket counts → `logs-count-ranges`.
- Distribution of a dimension (which services emit the errors?) → `logs-facet-values-create`.
- Use **this** tool to summarize message _content_ — what distinct things the logs say and how often.

# Reading the response

- `pattern` — the mined template. Masked tokens: `<uuid>`, `<ip>`, `<hex>`, `<num>`, and `<*>` for any word position that varied.
- `estimated_count` / `estimated_error_count` — occurrences extrapolated to the full window. When `sampled` is false these are exact.
- `severity_counts` — sampled occurrences per severity. A template split across `info` and `error` often means the same code path logging both outcomes.
- `services` — up to 4 service names the pattern was seen in.
- `match_regex` — a regex over raw log bodies that matches this pattern's lines, pre-validated against the raw bodies of the pattern's own sampled rows. Null when no trustworthy regex could be compiled. For JSON logs the pattern is mined from the extracted message field, so the regex may be unanchored (the message is a substring of the raw line) — it still targets the raw stored body.
- `match_literal` — longest literal run of the template, a plain-text fallback when `match_regex` is null.

Mining samples the window (`sampled: true` when it did): counts are estimates, and rare patterns (below roughly 1 in `scanned_count` of the volume) may be missing entirely. Narrow the `dateRange` or filters to mine a finer-grained sample.

## Pivoting to a pattern's raw lines

To fetch the lines behind a pattern, call `query-logs` with a message filter in `filterGroup`:

- If `match_regex` is set: `{ "key": "message", "value": "<match_regex>", "operator": "regex", "type": "log" }`
- Else if `match_literal` is set: `{ "key": "message", "value": "<match_literal>", "operator": "icontains", "type": "log" }`

Also pass the pattern's `services` as `serviceNames` and (when every entry is one of trace/debug/info/warn/error/fatal) the keys of `severity_counts` as `severityLevels` — both make the query dramatically cheaper.

# Parameters

## query.dateRange

Date range to mine. Defaults to the last hour (`-1h`).

- `date_from`: ISO 8601 timestamp or relative format: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: Same format. Omit or null for "now".

## query.severityLevels

Mine only these severities: `trace`, `debug`, `info`, `warn`, `error`, `fatal`. Omit to include all levels.

## query.serviceNames

Restrict mining to these services. Recommended once you know the target service — it prunes the scan and spends the whole sample budget on one service's templates.

## query.searchTerm

Full-text search over log bodies applied before mining. Useful to mine only the sub-stream around a keyword (e.g. `timeout`).

## query.filterGroup

Property filters applied before mining. Same format as `query-logs` filters.

# Examples

## What is this stream saying? (last hour, everything)

```json
{ "query": { "dateRange": { "date_from": "-1h" } } }
```

## Dominant error templates during an incident

```json
{
  "query": {
    "severityLevels": ["error", "fatal"],
    "dateRange": { "date_from": "2024-01-15T09:00:00Z", "date_to": "2024-01-15T11:00:00Z" }
  }
}
```

## Mine one service's logs around a keyword

```json
{
  "query": {
    "serviceNames": ["checkout"],
    "searchTerm": "payment",
    "dateRange": { "date_from": "-6h" }
  }
}
```
