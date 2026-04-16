# Configuration reference

The stripe-mock service is configured via `stripe-mock.config.yaml` in the service root.
All values are optional — defaults match the `revenue_analytics` scenario.
Changes take effect on restart (uvicorn `--reload` picks up file changes automatically).

## Timeline

### `start_date`

**Default:** `"2024-03-01"`

Start date for data generation. All customer subscriptions begin on or after this date.
Changing this shifts the entire dataset forward or backward in time.

```yaml
start_date: '2023-01-01' # Generate 3+ years of data
```

### `end_date`

**Default:** `"2026-03-01"`

End date for data generation. No invoices or charges are created after this date.
Subscriptions that would extend past this date are capped.

```yaml
end_date: '2025-06-01' # Shorter dataset
```

### `seed`

**Default:** `42`

Random seed for deterministic data generation.
Same seed always produces identical output. Change it to get a different
but equally valid dataset.

```yaml
seed: 123
```

## Customer configuration

### `customer_metadata`

**Default:** `{}` (empty)

Key-value pairs injected into the `metadata` field of every generated customer.
Useful for tagging mock data or testing metadata-based filters.

```yaml
customer_metadata:
  source: 'stripe-mock'
  environment: 'development'
  team_id: '12345'
```

### `customer_types`

**Default:** See below

Controls how many customers of each persona type to generate.
Set any type to `0` to skip it entirely.

```yaml
customer_types:
  loyalists_monthly: 12 # Stable monthly subscribers
  loyalists_annual: 6 # Stable annual subscribers
  churners: 8 # Cancel after N months
  resubscribers: 1 # Cancel then resubscribe
  upgraders: 1 # Upgrade to higher tier
  downgraders: 1 # Downgrade to lower tier
  interval_switchers: 1 # Switch monthly → yearly
  coupon_users: 3 # Have discount coupons
  multi_currency_eur: 5 # EUR subscribers
  multi_currency_gbp: 2 # GBP subscribers
  multi_currency_jpy: 3 # JPY subscribers (zero-decimal)
  refund_recipients: 3 # Receive refunds
  trial_users: 2 # Start with free trial
  late_joiners: 11 # Join at staggered dates
  edge_combos: 1 # Unusual combinations
```

**Quick presets:**

- Minimal smoke test: set everything to 0 except `loyalists_monthly: 3`
- Churn-heavy: set `churners: 50`, reduce others
- Multi-currency focus: increase `multi_currency_*` counts

## Product catalog

### `products`

**Default:** 3 tiers × 4 currencies × 2 intervals = 24 prices

Controls the product catalog. Each tier has prices for every currency/interval combination.
Amounts are in minor units (cents for USD/EUR/GBP, yen for JPY).

```yaml
products:
  tiers: ['basic', 'standard', 'premium']
  currencies: ['usd', 'eur', 'gbp', 'jpy']
  intervals: ['month', 'year']
  prices:
    basic:
      monthly_usd: 699 # $6.99/mo
      yearly_usd: 6999 # $69.99/yr
      monthly_eur: 649
      yearly_eur: 6499
      monthly_gbp: 499
      yearly_gbp: 4999
      monthly_jpy: 790 # ¥790/mo (zero-decimal)
      yearly_jpy: 7900
    standard:
      monthly_usd: 1549 # $15.49/mo
      yearly_usd: 15499
      monthly_eur: 1299
      yearly_eur: 12999
      monthly_gbp: 1099
      yearly_gbp: 10999
      monthly_jpy: 1780
      yearly_jpy: 17800
    premium:
      monthly_usd: 2299 # $22.99/mo
      yearly_usd: 22999
      monthly_eur: 1999
      yearly_eur: 19999
      monthly_gbp: 1799
      yearly_gbp: 17999
      monthly_jpy: 2980
      yearly_jpy: 29800
```

## Coupons

### `coupons`

**Default:** 3 coupons (WELCOME20, BETA100, EMPLOYEE)

Defines discount coupons that coupon_users customers receive.

```yaml
coupons:
  WELCOME20:
    percent_off: 20
    duration_months: 3 # Applied to first 3 invoices
  BETA100:
    percent_off: 100 # Free for 12 months
    duration_months: 12
  EMPLOYEE:
    percent_off: 100
    duration: 'forever' # Free forever
```

## Behavioral parameters

### `churn_months`

**Default:** `[1, 2, 3, 4, 5, 6, 7, 9]`

Month numbers at which churner customers cancel. Each churner gets assigned
one value from this list (cycling if there are more churners than months).

```yaml
churn_months: [1, 3, 6] # All churners cancel within 6 months
```

### `trial_days`

**Default:** `[7, 14]`

Trial durations in days for trial_users. Alternates between values.

```yaml
trial_days: [7, 14, 30] # Add a 30-day trial variant
```

### `late_joiner_offsets`

**Default:** `[1, 3, 4, 6, 7, 9, 10, 12, 15, 18, 20]`

Month offsets from `start_date` at which late_joiners start their subscriptions.

```yaml
late_joiner_offsets: [6, 12, 18] # Only join at 6-month intervals
```

### `payout_frequency_months`

**Default:** `1`

How often payouts are generated (in months). Set to `2` for bi-monthly payouts.

### `stripe_fee_percent`

**Default:** `2.9`

Stripe's percentage fee applied to each charge for balance transaction calculations.

### `stripe_fee_fixed_cents`

**Default:** `30`

Stripe's fixed fee per transaction in cents.

## Error injection

### `errors`

**Default:** `{}` (no errors)

Make specific API routes return errors to test resiliency.
Each key is a URL path prefix, and the value configures the error response.

```yaml
errors:
  '/v1/charges':
    status: 500 # HTTP status code
    message: 'Internal server error' # Error message in response body
    rate: 1.0 # Probability (0.0 to 1.0)

  '/v1/customers/search':
    status: 429
    message: 'Rate limit exceeded'
    rate: 0.5 # 50% of requests fail

  '/v1/invoices':
    status: 403
    message: 'Insufficient permissions'
    rate: 0.1 # 10% failure rate
```

**Use cases:**

- `rate: 1.0` — route always fails (test error handling paths)
- `rate: 0.5` — intermittent failures (test retry logic)
- `status: 429` — simulate rate limiting
- `status: 500` — simulate server errors
- `status: 403` — simulate permission errors
