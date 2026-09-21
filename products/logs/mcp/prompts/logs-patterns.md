Mine recurring log templates ("patterns") from the logs matching a filter set, ordered by frequency. Each pattern is a message template with the variable parts masked — e.g. `Connected to <ip> in <num>ms` — plus occurrence estimates, severity mix, the services it appears in, and a ready-made predicate for fetching its matching lines.

All parameters go inside `query` — top-level fields are rejected:

```json
{ "query": { "serviceNames": ["api"], "dateRange": { "date_from": "-1h" } } }
```

This is the fastest way to understand what a log stream is _saying_ without reading raw rows: one call summarizes millions of lines into templates.

The response is bounded for you, because one template can be a whole stack trace or a serialized query. You get the 20 highest-volume pattern groups, each held inside 400 characters. `omitted_pattern_count` says how many groups that left out, and every bound reports itself per pattern (see "Reading the response"). Raise `limit` for more groups, or set `maxPatternChars` to 0 to read whole templates.

# When to use

- To triage an unfamiliar or noisy stream: mine the last hour, scan the top templates by `estimated_count`, and look for anything with a non-zero error share in `severity_counts`.
- To find what's new or dominant during an incident window: mine with `severityLevels: ["error", "fatal"]` and a `dateRange` covering the incident.
- As the entry point of a drill-down loop: mine → pick a suspicious pattern → filter logs to exactly its lines using `match_patterns`, or `match_regex` and `match_literal` when it is empty (see below) → read the raw rows with `query-logs`.
- To quantify repetition before proposing log sampling or cleanup: `volume_share_pct` tells you how much of the stream one template accounts for.

## Pick the right tool

- Raw log lines matching a filter → `query-logs`.
- A single number (how many logs match) → `logs-count`; per-time-bucket counts → `logs-count-ranges`.
- Distribution of a dimension (which services emit the errors?) → `logs-facet-values-create`.
- Use **this** tool to summarize message _content_ — what distinct things the logs say and how often.

# Reading the response

- `source` reports what was used: `stored_patterns` for exact stored-pattern aggregation followed by Drain3 grouping, or `body_mining` for body masking and Drain3. Include this distinction in your answer.
- `pattern_version` identifies the version used for stored patterns. `fallback_reason` explains body mining: flag disabled, insufficient version coverage, an empty window, or comparison mode.
- The `logs_patterns_query_v2` flag enables the stored-pattern path only when one version supplies nonempty patterns for at least 99% of **all** matching rows. This is the dominant version, not necessarily the newest.
- On the stored-pattern path, `represented_count` counts the rows in the returned groups. `remainder_count` accounts for other versions, unstamped rows, the long tail and groups outside the display limit. Report this remainder rather than implying the returned groups cover everything.
- `pattern` — the template. Body mining masks `<uuid>`, `<ip>`, `<hex>`, `<num>`, and `<*>` for any word position that varied. Stored patterns use the ingestion vocabulary instead: `<N>`, `<TIMESTAMP>`, `<KLOGTIME>`, `<UUID>`, `<IP>`, `<HOST>`, `<HEX>`, `<ID>`, `<EMAIL>`, `<JSON_ARRAY>`, and `<JSON:keys>` for a JSON body reduced to its key set.
- `estimated_count` / `estimated_error_count` — occurrences extrapolated to the full window. When `sampled` is false these are exact.
- `severity_counts` — occurrences per severity, never extrapolated: sample counts when `sampled` is true, exact counts over every matching row otherwise. A template split across `info` and `error` often means the same code path logging both outcomes.
- `services` — up to 4 service names the pattern was seen in.
- `match_regex` — a regex over raw log bodies that matches this pattern's lines, pre-validated against the raw bodies of the pattern's own sampled rows. Always null on the stored-pattern path, which pivots with `match_patterns` instead, and null on the mining path when no trustworthy regex could be compiled. For JSON logs the pattern is mined from the extracted message field, so the regex may be unanchored, because the message is a substring of the raw line. It still targets the raw stored body.
- `match_literal` — longest literal run of the template, a plain-text fallback when `match_regex` is null. Also null on the stored-pattern path.

The bound fields say what the response left out, so you never read a cut template as the whole one:

- `returned_pattern_count` / `omitted_pattern_count` — groups in `patterns`, and mined groups the `limit` bound dropped. The dropped ones are always the lowest-volume.
- `pattern_truncated` — the template was cut and ends in a marker saying so. Its match fields still target the pattern's whole lines.
- `match_patterns_omitted` — canonical members dropped from the pivot. The returned members stay exact, so a filter on them reads their lines and no others, but it covers part of the group.
- `match_regex_omitted` — the regex was over budget and is withheld rather than shortened, because a cut regex matches nothing. Pivot on `match_literal`, or re-run with `maxPatternChars` set to 0.
- `match_literal_truncated` — the literal was cut to a prefix. An icontains filter on the prefix still matches every line of the pattern, plus any other line that contains the prefix.

Mining samples the window (`sampled: true` when it did): counts are estimates, and rare patterns (below roughly 1 in `scanned_count` of the volume) may be missing entirely. Narrow the `dateRange` or filters to mine a finer-grained sample.

## Pivoting to a pattern's raw lines

To fetch the lines behind a pattern, call `query-logs` with the appropriate filters in `filterGroup`:

- If `match_patterns` is nonempty, use **both** exact filters instead of a message predicate: `{ "key": "pattern", "value": ["<canonical member>", "..."], "operator": "exact", "type": "log" }` and `{ "key": "pattern_version", "value": 3, "operator": "exact", "type": "log" }`. Substitute the returned members and version, and combine the filters with AND. Keep the original time range and filters. Do not narrow these exact groups using example services or severities.
- If `match_regex` is set: `{ "key": "message", "value": "<match_regex>", "operator": "regex", "type": "log" }`
- Else if `match_literal` is set: `{ "key": "message", "value": "<match_literal>", "operator": "icontains", "type": "log" }`

For body-mined patterns, also pass the pattern's `services` as `serviceNames` and (when every entry is one of trace/debug/info/warn/error/fatal) the keys of `severity_counts` as `severityLevels` — both make the query dramatically cheaper.

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

## query.limit

Highest-volume pattern groups to return. Defaults to 20 over MCP, and is held down to the miner's own cap of 200. Raise it when `omitted_pattern_count` is nonzero and the long tail matters.

## query.maxPatternChars

Character budget for each group's template and match predicates. Defaults to 400 over MCP. Pass 0 for whole templates, which is the right call for one pattern you have already picked, not for a first survey of the stream. A nonzero budget must be 80 or greater, because a smaller one cannot carry the cut marker.

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

## Read one pattern's whole template

```json
{
  "query": {
    "serviceNames": ["api"],
    "searchTerm": "payment provider timeout",
    "limit": 3,
    "maxPatternChars": 0,
    "dateRange": { "date_from": "-1h" }
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
