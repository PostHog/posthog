import { humanFriendlyCurrency } from 'lib/utils/numbers'

/** 1 credit = $0.01. Amounts arrive from the API as integer credits. Credits are the unit we bill,
 * so we lead with the credit count and anchor it with the dollar value to keep the cost transparent. */
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

/** A "used of limit" pair with the dollars anchored once so the sentence stays readable,
 * e.g. (1200, 5000) -> "1,200 of 5,000 credits (≈ $12.00 of $50.00)". */
export function formatCreditsRange(used: number, total: number): string {
    return `${Math.round(used).toLocaleString('en-US')} of ${formatCreditCount(total)} (≈ ${creditsToUsd(
        used
    )} of ${creditsToUsd(total)})`
}
