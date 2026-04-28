# Finding types

## Severities

| Severity | Badge | Meaning                                                                           |
| -------- | ----- | --------------------------------------------------------------------------------- |
| CRITICAL | 🔴    | Blocks correctness — experiment results may be invalid or flag behavior is broken |
| WARNING  | 🟡    | Needs attention — not broken yet but risks exist or best practices are violated   |
| INFO     | 🔵    | Suggestion — hygiene improvement, safe to defer                                   |

## Finding categories

| Category    | Description                                                                                        | Max severity |
| ----------- | -------------------------------------------------------------------------------------------------- | ------------ |
| Correctness | Integrity issues that affect experiment results or flag evaluation                                 | CRITICAL     |
| Waste       | Active resources not serving a purpose (running experiments going nowhere, flags nobody evaluates) | WARNING      |
| Process     | Methodology and practice issues (missing hypothesis, no metrics)                                   | WARNING      |
| Complexity  | Fragility and maintainability concerns (too many toggles, high churn)                              | WARNING      |
| Cleanup     | Hygiene items — stale drafts, orphaned flags, safe to defer                                        | INFO         |
| Security    | PII or access concerns in flag/experiment configuration                                            | WARNING      |

## Severity caps

Never assign a severity higher than the category's max:

- A **Cleanup** finding is always INFO, never WARNING or CRITICAL.
- A **Correctness** finding can be CRITICAL, WARNING, or INFO depending on impact.
- A **Waste** or **Process** finding caps at WARNING.

## Finding format

When reporting a finding, always include:

1. **Severity** — one of CRITICAL, WARNING, INFO
2. **Category** — one of the categories above
3. **Check name** — which check produced this (e.g., "Metric setup", "Flag integration")
4. **Entity** — which experiment or flag, as a markdown link
5. **Description** — one sentence explaining what's wrong
6. **Action** — one sentence explaining what to do (reference [remediation actions](./remediation-actions.md))

### Ordering

When listing multiple findings:

1. Sort by severity: CRITICAL first, then WARNING, then INFO.
2. Within the same severity, group by entity.
3. Within the same entity, list by category: Correctness → Waste → Process → Complexity → Cleanup → Security.
