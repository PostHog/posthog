Run a trends query and return each series in the shape of a Prometheus range result, for a client that draws a chart from that shape.

Use it when the person wants to see a trend over time as a chart. For every other question use `query-trends`, which returns a summary that is easier to read.

The input is the same as `query-trends`, without `output_format`. Run `info query-trends` for the fields, the schema-first workflow and the examples.

A query that returns values over time returns JSON in this shape:

```text
{ "results": [{ "metric": { "series": "$pageview", "breakdown": "Chrome" }, "values": [["2026-01-01", 120]] }] }
```

`metric` holds the series name, with the breakdown value under `breakdown` and the comparison period under `compare` when the query has them. `values` holds one `[date, value]` pair per interval.

A total-value display, such as `BoldNumber`, `ActionsPie` or `ActionsTable`, has no dates to draw, so it returns the same results as `query-trends` with `"output_format": "json"`.
