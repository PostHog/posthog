# Error tracking facade contract-check

`_contract_check.py` freezes the public surface of
`products.error_tracking.backend.facade` against a committed lock file at
`products/error_tracking/backend/facade/.contract-lock.json`.

The check walks every name exported by `facade.__all__` and records:

- **Contract dataclasses** — frozen flag, field names, field type strings.
- **Public functions / coroutines** — parameter kinds, annotations,
  `default` presence, return annotation.
- **Classes** (e.g. `SearchErrorTrackingIssuesTool`) — qualname and base
  class names.

## What breaks the check

- Removing a dataclass field
- Changing a dataclass field type
- Removing a `@dataclass(frozen=True)` marker
- Removing a public function or class from `__all__`
- Renaming or removing a function parameter
- Changing a function parameter's annotation
- Changing a function return annotation
- Adding a new **required** (no default) function parameter

Additions (new contracts, new fields with safe defaults, new optional
parameters, new classes in `__all__`) are allowed — they appear in the
new snapshot and the `--update` flag will include them next time.

## Running locally

```bash
pnpm --filter @posthog/products-error-tracking backend:contract-check
# or directly
python products/error_tracking/backend/facade/_contract_check.py
```

Expected output on a clean working tree:

```text
Error tracking facade contract-check passed.
```

## Intentionally bumping the lock file

When a breaking change is genuinely intended (e.g. a contract field is
being renamed as part of a coordinated refactor), run:

```bash
python products/error_tracking/backend/facade/_contract_check.py --update
```

Review the updated `.contract-lock.json` diff, commit it with the
breaking change in the **same** PR, and call out the breaking change in
the PR description so downstream consumers know to update.

## How the check runs in CI

The script is wired into `products/error_tracking/package.json` under
`backend:contract-check`. CI should invoke this script for any PR that
touches `products/error_tracking/backend/facade/**`.
