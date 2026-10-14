/** Shared by every "Limit reached" badge so the surfaces tell one story. */
const LIMIT_REACHED_TOOLTIP =
    'This scanner stopped scanning until its credit limit resets at the start of the next billing period. ' +
    'Sessions skipped while capped are not scanned later.'

const FREE_CREDITS_USED_TOOLTIP =
    'This scanner only uses free credits, and your organization has used them for this billing period. ' +
    'It starts again when the period resets. Sessions skipped until then are not scanned later. ' +
    'To keep scanning now, turn off "Free credits only" in its settings. ' +
    "If your organization's spend limit is used up too, raise it in billing as well."

type LimitFields =
    | { free_only?: boolean; credit_limit?: number | null; limit_from_free_credits?: boolean }
    | null
    | undefined

// The free credits stop a free-only scanner when it has no limit of its own, or when they leave less room than it.
export function stoppedByFreeCredits(scanner: LimitFields): boolean {
    return !!scanner?.free_only && (scanner.credit_limit == null || !!scanner.limit_from_free_credits)
}

export function limitReachedTooltip(scanner: LimitFields): string {
    return stoppedByFreeCredits(scanner) ? FREE_CREDITS_USED_TOOLTIP : LIMIT_REACHED_TOOLTIP
}

export function limitReachedLabel(scanner: LimitFields): string {
    return stoppedByFreeCredits(scanner) ? 'Free credits used' : 'Limit reached'
}
