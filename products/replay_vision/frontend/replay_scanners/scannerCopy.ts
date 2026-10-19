/** Shared by every "Limit reached" badge so the surfaces tell one story. */
const LIMIT_REACHED_TOOLTIP =
    'This scanner stopped scanning until its credit limit resets at the start of the next billing period. ' +
    'Sessions skipped while capped are not scanned later.'

const FREE_CREDITS_USED_TOOLTIP =
    'Paused until your free credits reset. Recordings until then are skipped. ' +
    'To keep scanning, turn off "Free credits only" on the scanner page.'

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
