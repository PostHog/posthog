# Task spec convention

Each task lives in `products/signals/eval/self_driving/tasks/<task_id>/` and is a self-contained customer universe.

## `task.json`

```jsonc
{
  "task_id": "checkout-coupon-case", // kebab-case, unique; also the repo dir name
  "title": "Lowercase coupon codes 500 at checkout",
  "family": "logic", // logic | api-contract | frontend-state | perf | data-integrity | config
  "difficulty": "T1", // T1 direct | T2 indirect | T3 adversarial
  "repo_full_name": "acme/checkout-coupon-case", // synthetic GitHub name; org is always "acme"
  "signal_type": "zendesk", // zendesk | github | linear | conversations | pganalyze
  "product_summary": "Acme Store checkout service (Node/Express)",
  "ground_truth": {
    "root_cause": "getCoupon() only trims the code and never uppercases it, despite the marketing emails printing codes lowercase; lookup misses and applyCoupon throws, surfacing as a 500 on POST /api/cart/:id/coupon.",
    "culprit_files": ["src/coupons.js"],
    "fix_contract": "Coupon codes must be accepted case-insensitively; applying 'save10' to a 8400-cent cart returns 7560 and a 200 response. Unknown codes must still 4xx/error cleanly, not 500.",
    "expected_evidence": [
      "$exception events with message 'Unknown coupon: save10' concentrated after the campaign send",
      "coupon_applied events only for uppercase codes",
    ],
    "distractors": [
      "recent commit touching cart totals (innocent)",
      "unrelated 404s on /api/cart/:id for expired carts",
    ],
    "immediately_actionable": true,
    "priority": "P2",
  },
  "seed": {
    // consumed by harness/seed.py
    "days": 3,
    "streams": [
      {
        "kind": "funnel",
        "events": ["checkout_started", "coupon_attempted", "checkout_completed"],
        "daily": [220, 140, 96],
        "drop_after": { "event": "coupon_attempted", "from_hours_ago": 30, "to_daily": 15 },
      },
      {
        "kind": "exception",
        "message": "Unknown coupon: save10",
        "type": "Error",
        "source": "src/coupons.js",
        "daily": 0,
        "burst": { "from_hours_ago": 30, "count": 180 },
      },
      { "kind": "custom", "event": "coupon_applied", "properties": { "code": "SAVE10" }, "daily": 45 },
    ],
  },
}
```

## `signals.json`

Records in the exact wire format of the chosen `signal_type` fixture
(for zendesk: `id, subject, description, url, type, tags (JSON string), created_at, priority, status`).
1-3 records per task; they should read like real customers/CX agents wrote them —
partial knowledge, symptoms not causes, occasionally wrong hypotheses (required for T2/T3).

## `repo/`

A complete runnable product repo (committed files only, no `.git` — the harness inits git and
commits as `dana-acme <dana@acme.test>` with a plausible history: the defect must NOT be the HEAD commit
for T2/T3; add 2-4 innocent commits after it).
Rules:

- Must be plausible: package.json/pyproject, README, a few modules beyond the defective one.
- Must be instrumented with posthog client calls matching the seeded event names (the researcher cross-references code ↔ data).
- Defect must be findable from evidence, not from comments — never comment the bug itself. A misleading
  or stale comment near the defect is allowed (and encouraged at T3).
- Keep it small: 5-15 source files, no lockfiles, deps limited to express/posthog-node or stdlib.

## `verify/`

Hidden behavioral tests, DeepSWE-style — behavior, not symbols:

- `verify/test_fix.mjs` (or `.py`): node:test / pytest exercising the **fix contract** through the public
  surface (HTTP endpoint, exported function). Must FAIL on the unpatched repo and PASS on a correct fix.
- `verify/test_regressions.mjs`: pre-existing behavior that must keep passing (fails only if the patch breaks it).
- Tests are copied into a scratch checkout at grade time; they never enter the sandbox.
- Top of each file: a comment stating the regression it catches.

## Authoring checklist

1. `node --test verify/` on the pristine repo: fix tests fail, regression tests pass.
2. Apply the reference fix mentally (or actually) — all tests pass.
3. Signal text mentions the _symptom_ in customer language; grep the repo for the exact signal phrases —
   they must not trivially locate the culprit line at T2+.
4. Seed spec events match the repo's instrumentation names exactly.
