# common-ingestion-response

The response contract between ingestion and the batch services it calls, such as Cymbal. A service reports a result for each item in a request, so one bad item fails only itself instead of the whole request, and it can attach ingestion warnings for the team that sent the item.

## Opting in

The client sends `X-PostHog-Ingestion-Response: 1`.

A server that supports version 1 answers with `X-PostHog-Ingestion-Response: 1` and a body in the shape below. A server that does not support it ignores the header and answers the old way. A client must therefore pick its parser from the response header, not from what it sent.

## Response body

```json
{
  "results": [
    {
      "result": "ok",
      "value": {"...": "service payload"},
      "warnings": [{"type": "error_tracking_exception_processing_errors", "details": {"...": "..."}, "key": "..."}]
    },
    {"result": "drop", "reason": "suppressed"},
    {"result": "retry", "error": {"code": "deadline_exceeded", "message": "..."}},
    {"result": "fail", "error": {"code": "invalid_input", "message": "..."}}
  ]
}
```

- `results` has exactly one entry per request item, in request order. A client must treat any other length as a failure of the whole request.
- `ok`: the item succeeded. `value` is the service's own payload.
- `drop`: the service skipped the item on purpose. `reason` is a snake_case label.
- `retry`: the item failed for a reason that may clear later.
- `fail`: the item can never succeed as sent.
- `error.code` is a snake_case machine label. The shared codes are `invalid_input` and `deadline_exceeded`. A service may add its own.
- `error.message` is for humans and logs. Clients must not parse it.
- Clients use `reason` and `error.code` as metric labels, so a service keeps each to a small, fixed set.
- Adding a `result` kind or changing what a field means needs a new protocol version. A client must treat a result it does not recognize as a failure of the whole request. A new optional field does not need a new version, because both sides ignore fields they do not know.

## Warnings

Any result can carry `warnings`, which ingestion shows to the team as ingestion warnings.

- `type` is a type in the ingestion warnings registry, `nodejs/src/ingestion/common/ingestion-warning-types.ts`. Rust services get the same list from `common-ingestion-warnings`.
- `details` is an object that the warning type defines.
- `key` is optional. Ingestion rate-limits warnings per team, type and key, so a key per item keeps one item's warning from hiding another's.
- A client skips a warning whose type it does not know and keeps the item's result, so a service can deploy a new warning type before ingestion does.

## Whole-request failures

Only a 2xx response carries item results and echoes the header. Other status codes keep their meaning for the request as a whole:

- 429 and 503, with an optional `Retry-After`, and other 5xx: retry the whole request.
- Other 4xx: the request itself is malformed.

A server uses these only when the failure is not specific to an item, for example when a database or a downstream pool is unavailable. It must not report that kind of failure as a `retry` for every item. A client should still treat a batch where every item is `retry` as a failure of the whole request, and never drop data because of it. When a client splits one batch over several requests, it applies this rule to the whole batch and not to each response, because one request can hold a single slow item.

## Implementations

- Rust servers: this crate. `PerItemResults` extracts the opt-in from an axum request, and `ItemResults` checks the length and answers with the header.
- Node ingestion: `nodejs/src/ingestion/common/service-response.ts` parses a response and turns each result into a pipeline result. A `fail` or `retry` item goes to the DLQ, its warnings become ingestion warnings, and the all-retry rule fails the batch.
