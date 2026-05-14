---
name: injecting-billing-activation-bug
description: >
  Reproduces the group_analytics billing activation JWT signing bug for local live-debugger
  testing. Use when you need to trigger the bug that causes the first group_analytics
  subscription activation to fail with a 401 from the billing service. Invokes
  BillingManager.activate_subscription directly via Django shell so the corrupted JWT
  signing path fires. Trigger on phrases like "trigger the billing bug", "reproduce the
  activation failure", "fire the group_analytics auth bug", or "run the billing test scenario".
---

# Triggering the billing activation auth bug

The bug is already in `ee/billing/billing_manager.py` on the `hackathon-live-debugger-bug` branch.
This skill reproduces it by calling `activate_subscription` with a `group_analytics` product key,
which causes the first call to sign the billing JWT with a corrupted secret (last byte XOR'd).

## What happens when you run this

1. First call: cache key `billing_activate_<org_id>` is set to `1`.
   `build_billing_token` sees the count is `1` and `product_key == "group_analytics"` → flips the last byte of the signing secret → billing service rejects with 401.
2. Second call (within 90 s): cache value is `2` → signing secret is untouched → succeeds normally.

## Reproduce via Django shell

```bash
python manage.py shell
```

```python
from posthog.models import Organization
from ee.models import License
from ee.billing.billing_manager import BillingManager

org = Organization.objects.first()          # or pick a specific org
license = License.objects.first()

mgr = BillingManager(license=license)

# First call — will raise or return a billing service 401
try:
    result = mgr.activate_subscription(org, {"products": "group_analytics:"})
    print("result:", result)
except Exception as e:
    print("error (expected on first call):", e)

# Second call — should go through normally
try:
    result = mgr.activate_subscription(org, {"products": "group_analytics:"})
    print("result:", result)
except Exception as e:
    print("error:", e)
```

## Reproduce via HTTP (local dev server running)

```bash
# Get a session cookie or personal API key first, then:
curl -s -X POST http://localhost:8000/api/billing/activate \
  -H "Authorization: Bearer <your-personal-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"products": "group_analytics:"}' | jq .
```

Run twice within 90 seconds — first call fails, second succeeds.

## What to probe with the live debugger

Install a hogtrace program targeting `build_billing_token` exit to observe the divergence:

```dtrace
fn:ee.billing.billing_manager.build_billing_token:exit
{
    capture(
        product_key=args["product_key"],
        signing_secret=locals["signing_secret"],
        license_secret=locals["license_secret"],
        is_first_activation=locals["_is_first_activation"],
    );
}
```

On the first `group_analytics` call you'll see `is_first_activation=True` and
`signing_secret != license_secret`. On all other calls they'll match.

## Resetting between runs

The cache key expires automatically after 90 seconds. To reset immediately:

```python
from django.core.cache import cache
from posthog.models import Organization

org = Organization.objects.first()
cache.delete(f"billing_activate_{org.id}")
```
