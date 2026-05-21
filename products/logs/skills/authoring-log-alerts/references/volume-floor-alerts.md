# Volume-floor alerts (`threshold_operator: below`)

Use to alert when a service _stops_ producing logs — a strong signal that the service is down, the logging
pipeline is broken, or something upstream stopped sending traffic.

## When to use

- The user says "tell me if X stops logging."
- A service has dependably constant volume across all hours (no nightly drop, no weekend drop) and the user
  cares about availability.

## When NOT to use

- The service has any quiet hours (overnight, weekends, batch-only). Below-threshold alerts will fire every
  quiet period.
- The service is bursty by design — a 5-minute "no logs" window is normal.
- You don't have at least 7 days of stable baseline. With less data, "below normal" is unknowable.

## How to size the threshold

The `baseline_stats.py` script doesn't suggest below-thresholds directly — derive it manually from the
script's output. Don't compute by hand; use Python:

```bash
python3 -c "import sys, json; d=json.load(sys.stdin); print(max(1, round(d['stats']['p50'] * (5/d['bucket_minutes']) * 0.25)))" < stats.json
```

The reasoning:

1. Take `p50` from the script (the typical bucket count).
2. Rate-scale to the alert window (`window_minutes / bucket_minutes`).
3. Multiply by 0.25 — fire when volume drops to 25% of the typical bucket. Buffer absorbs normal variance.
4. Set `threshold_operator: below`.

## Recommended N-of-M for floors

- `evaluation_periods: 3`, `datapoints_to_alarm: 3` (3-of-3) — require 3 consecutive quiet windows. A single
  blip won't fire.
- `window_minutes: 15` minimum — 5-minute floor alerts on noisy services are unreliable.
- `cooldown_minutes: 60` — once you know the service is quiet, no point re-paging every check.

## Simulate is essential here

Floor alerts are easy to misconfigure into "fires every night." Always run `posthog:logs-alerts-simulate-create` over `-7d`
before shipping. If `fire_count > 0` and the user has not had outages in the last 7 days, the threshold is
too aggressive.
