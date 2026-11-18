import type { ReplayScannerApi } from '../generated/api.schemas'

const RAISE_FACTOR = 1.5
const FIRST_LIMIT_CREDITS = 500
const STEP_CREDITS = 100

export type SuggestedCreditLimitInput = Pick<
    ReplayScannerApi,
    | 'credit_limit'
    | 'credits_this_month'
    | 'credits_used_against_limit'
    | 'limit_from_free_credits'
    | 'credits_per_observation'
>

/** The monthly limit to offer a capped scanner. The limit counts the credits the scanner already spent in this
 * period, so a suggestion below that spend saves but leaves the scanner capped. */
export function suggestedCreditLimit(scanner: SuggestedCreditLimitInput): number {
    // When the free credits bind, `credits_used_against_limit` is the organization's usage, not the scanner's.
    const spent = scanner.limit_from_free_credits ? scanner.credits_this_month : scanner.credits_used_against_limit
    const base = Math.max(scanner.credit_limit ?? 0, spent)
    const target = Math.max(
        base > 0 ? base * RAISE_FACTOR : FIRST_LIMIT_CREDITS,
        spent + scanner.credits_per_observation
    )
    return Math.ceil(target / STEP_CREDITS) * STEP_CREDITS
}
