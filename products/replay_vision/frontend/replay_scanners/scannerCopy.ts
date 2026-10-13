/** Shared by every "Limit reached" badge so the surfaces tell one story. */
const LIMIT_REACHED_TOOLTIP =
    'This scanner stopped scanning until its credit limit resets at the start of the next billing period. ' +
    'Sessions skipped while capped are not scanned later.'

const FREE_CREDITS_USED_TOOLTIP =
    'This scanner only uses free credits, and your organization has used them for this billing period. ' +
    'It starts again when the period resets. Sessions skipped until then are not scanned later. ' +
    'To keep scanning now, turn off "Free credits only" in its settings.'

type LimitFields = { free_only?: boolean; credit_limit?: number | null } | null | undefined

// The API only says a scanner stopped, so the free-credits copy needs the free credits to be its only limit.
function stoppedByFreeCredits(scanner: LimitFields): boolean {
    return !!scanner?.free_only && scanner.credit_limit == null
}

export function limitReachedTooltip(scanner: LimitFields): string {
    return stoppedByFreeCredits(scanner) ? FREE_CREDITS_USED_TOOLTIP : LIMIT_REACHED_TOOLTIP
}

export function limitReachedLabel(scanner: LimitFields): string {
    return stoppedByFreeCredits(scanner) ? 'Free credits used' : 'Limit reached'
}
