/**
 * What to show when the refund button is visible but the backend already knows the refund would be
 * refused (`refund_ineligibility_reason`). The desktop client keeps the same table in
 * `products/desktop/packages/core/src/inbox/refundEligibility.ts`.
 */
export interface RefundBlock {
    copy: string
    /** True when support can still credit this PR back, so the reader has a next step. */
    routesToSupport: boolean
}

// `already_refunded` / `billing_exempt` never reach the button (it's hidden for those), so only the
// two visible-but-ineligible reasons map.
const REFUND_BLOCKED_COPY: Record<string, string> = {
    out_of_period:
        "This PR was billed in an earlier billing period, so it can't be refunded here. Support can credit it back for you.",
    no_billable_pr: "This PR isn't billable, so there's nothing to refund",
}

const REFUND_BLOCKED_FALLBACK_COPY = "This PR can't be refunded right now"

// Reasons a person can still act on. The refund window is the org's billing period, so a PR billed
// before it needs a billing-service credit, which only support can issue. Every other reason has no
// next step, so the button stays a disabled explanation.
const REFUND_SUPPORT_ROUTE_REASONS = new Set(['out_of_period'])

export function refundBlockFor(reason: string | null | undefined): RefundBlock | null {
    if (!reason) {
        return null
    }
    return {
        copy: REFUND_BLOCKED_COPY[reason] ?? REFUND_BLOCKED_FALLBACK_COPY,
        routesToSupport: REFUND_SUPPORT_ROUTE_REASONS.has(reason),
    }
}
