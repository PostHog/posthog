"""Revenue analytics view builders for the Checkout.com warehouse source.

Checkout.com's data model differs from Stripe's, so only the view kinds its data can
genuinely support are registered:

- charge and revenue_item map onto `payments` + `payment_actions` (a charge is an
  approved `Capture` action; refunds are `Refund` actions in the same table and are
  not netted, matching the Stripe builder's gross-revenue semantics).
- customer maps onto `customers`, with the cohort derived from `payments`.

Checkout.com has no product, subscription or invoice objects, so the product,
subscription and MRR views are not registered — the orchestrator only builds the view
kinds present in this dict. Settlement-level figures (fees, payouts) exist in the
`financial_actions_report` table at (`action_id`, `breakdown_type`) grain, but its
column set is account-configurable, so no managed view is built on it.
"""
