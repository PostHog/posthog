import { humanFriendlyCurrency } from 'lib/utils/numbers'

/** 1 credit = $0.01. Amounts arrive from the API as integer credits. Credits are the unit we bill, so credits are
 * what we show. The dollar anchor is reserved for the three spend surfaces (the spend meter, the scanner list's
 * spend column, and the cost estimate) — repeating it in every tooltip, banner, and dropdown option is noise.
 * Those three pair `formatCreditCount` with `creditsToUsd` when the dollar gets its own line, or use the inline
 * `formatCredits`. Everywhere else is `formatCreditCount` alone. */
export const CREDITS_PER_DOLLAR = 100

/** e.g. 1200 -> "$12.00". */
export function creditsToUsd(credits: number): string {
    return humanFriendlyCurrency(Math.round(credits) / CREDITS_PER_DOLLAR)
}

/** e.g. 500 -> "500 credits", 1 -> "1 credit". */
export function formatCreditCount(credits: number): string {
    const rounded = Math.round(credits)
    return `${rounded.toLocaleString('en-US')} ${Math.abs(rounded) === 1 ? 'credit' : 'credits'}`
}

/** e.g. 500 -> "500 credits (≈ $5.00)", 1 -> "1 credit (≈ $0.01)". */
export function formatCredits(credits: number): string {
    return `${formatCreditCount(credits)} (≈ ${creditsToUsd(credits)})`
}

/** A "used of limit" pair that names the unit once, e.g. (1200, 5000) -> "1,200 of 5,000 credits". */
export function formatCreditsRange(used: number, total: number): string {
    return `${Math.round(used).toLocaleString('en-US')} of ${formatCreditCount(total)}`
}
