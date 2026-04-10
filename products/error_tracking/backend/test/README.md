# Error tracking backend tests

Error tracking backend tests are being normalized around the product architecture over time.

Use these buckets when adding or moving tests:

- `facade/` — stable product-facing contract tests and client-safe projections
- `logic/` — business logic and model behavior without HTTP concerns
- `presentation/` — DRF/view/serializer behavior and request-response translation

This layout is intentionally incremental.
Existing query runner and tool tests can remain in their current locations until they are touched.
Avoid risky one-shot moves of the entire suite.
