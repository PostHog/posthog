# Customer types

Each customer type represents a distinct billing behavior pattern.
Together they exercise all the edge cases in PostHog Revenue analytics.

## Loyalists (monthly)

Stable monthly subscribers who never cancel.
They form the baseline MRR and are evenly split across tiers (basic/standard/premium).

**Config key:** `loyalists_monthly` (default: 12)

**What they produce:** One subscription per customer, one invoice + charge per month for the full date range.
This is the "healthy base" of recurring revenue.

**Revenue analytics edge cases tested:**

- Steady MRR calculation
- Per-tier revenue breakdown

## Loyalists (annual)

Same as monthly loyalists but on yearly billing.

**Config key:** `loyalists_annual` (default: 6)

**What they produce:** One subscription per customer, one invoice + charge per year.
The annual payment is the full yearly price in a single charge.

**Revenue analytics edge cases tested:**

- Annual subscriptions misclassified as monthly
- Deferred revenue spreading (one large payment spread over 12 months)

## Churners

Subscribers who cancel after a configurable number of months.

**Config key:** `churners` (default: 8)
**Related config:** `churn_months` controls when each churner cancels (default: `[1, 2, 3, 4, 5, 6, 7, 9]`)

**What they produce:** Subscription with `status: canceled`, `canceled_at` and `ended_at` timestamps.
Invoices/charges only for months before cancellation.

**Revenue analytics edge cases tested:**

- Churn rate calculation
- Churned MRR identification
- Early vs late churn distribution

## Resubscribers

Subscribers who cancel, then come back later.
Simulates win-back campaigns.

**Config key:** `resubscribers` (default: 1)

**What they produce:** Two separate subscriptions for the same customer:
one canceled at month 4, one new starting at month 8.
Gap in invoices between months 4 and 8.

**Revenue analytics edge cases tested:**

- Churn followed by reactivation
- MRR movements (churn then new)
- Multiple subscriptions per customer

## Upgraders

Start on a lower tier and upgrade mid-lifecycle.

**Config key:** `upgraders` (default: 1)

**What they produce:** Single subscription where the price changes at month 6
(e.g., basic to standard). Invoices before month 6 are at the lower price,
after month 6 at the higher price. Generates proration invoice items.

**Revenue analytics edge cases tested:**

- Expansion MRR
- Mid-cycle plan changes
- Proration handling

## Downgraders

Start on a higher tier and downgrade.

**Config key:** `downgraders` (default: 1)

**What they produce:** Single subscription where the price drops at month 5
(e.g., premium to standard).

**Revenue analytics edge cases tested:**

- Contraction MRR
- Revenue decrease without churn

## Interval switchers

Switch from monthly to yearly billing mid-lifecycle.

**Config key:** `interval_switchers` (default: 1)

**What they produce:** Monthly invoices for 8 months, then a single yearly invoice.
Tests how the system handles billing interval changes.

**Revenue analytics edge cases tested:**

- Monthly-to-annual conversion
- Change in invoice cadence
- Deferred revenue calculation after switch

## Coupon users

Subscribers with percentage discounts applied.

**Config key:** `coupon_users` (default: 3)
**Related config:** `coupons` defines available coupon definitions

**What they produce:** Invoices with reduced amounts for the first 3 months
(or longer, depending on coupon duration). The discount is applied as a
percentage off the unit amount.

**Revenue analytics edge cases tested:**

- Discounts not deducted from revenue (common bug)
- 100% discount showing as $0 revenue (beta testers, employees)
- Mix of percentage-off coupons

## Multi-currency (EUR, GBP, JPY)

Subscribers paying in non-USD currencies.

**Config keys:**

- `multi_currency_eur` (default: 5)
- `multi_currency_gbp` (default: 2)
- `multi_currency_jpy` (default: 3)

**What they produce:** Invoices and charges in their respective currencies.
JPY is a zero-decimal currency (amounts are in yen, not cents).

**Revenue analytics edge cases tested:**

- Currency conversion errors
- Zero-decimal currency handling (JPY)
- Multi-currency revenue aggregation

## Refund recipients

Customers who receive full or partial refunds.

**Config key:** `refund_recipients` (default: 3)

**What they produce:** Three variants:

1. Full refund at month 3, stays subscribed
2. Partial refund ($5) at month 6
3. Full refund + cancel at month 4

Each refund generates a `refund` object and a negative `balance_transaction`.

**Revenue analytics edge cases tested:**

- Refunds not subtracted from revenue (common bug)
- Partial vs full refunds
- Refund combined with churn (double negative event)

## Trial users

Subscribers who start with a free trial period.

**Config key:** `trial_users` (default: 2)
**Related config:** `trial_days` controls trial durations (default: `[7, 14]`)

**What they produce:** Two variants:

1. Trial that converts to paid (subscription has `trial_start`/`trial_end` fields)
2. Trial that cancels before converting (subscription canceled at month 0)

**Revenue analytics edge cases tested:**

- Trial-to-paid conversion tracking
- Trial churn (should show $0 revenue)
- `trialing` subscription status

## Late joiners

Subscribers who start at various points throughout the date range,
not at the beginning.

**Config key:** `late_joiners` (default: 11)
**Related config:** `late_joiner_offsets` controls start months (default: `[1, 3, 4, 6, 7, 9, 10, 12, 15, 18, 20]`)

**What they produce:** Staggered subscription start dates creating a realistic
MRR growth curve. Uses a mix of currencies.

**Revenue analytics edge cases tested:**

- MRR growth over time (not flat from day 1)
- New customer acquisition curve

## Edge combos

Unusual combinations that test boundary conditions.

**Config key:** `edge_combos` (default: 1)

**What they produce:** Currently generates an annual subscriber who upgrades
mid-year (annual basic to annual premium at month 6), testing proration
on yearly billing.

**Revenue analytics edge cases tested:**

- Annual plan upgrades with proration
- Mid-year tier changes on annual billing
