import type { ScannerOffReason } from './scannerStatus'

/** Shared by every "Limit reached" badge so the surfaces tell one story. */
export const LIMIT_REACHED_TOOLTIP =
    'This scanner stopped scanning until its credit limit resets at the start of the next billing period.'

type LimitFields =
    | { free_only?: boolean; credit_limit?: number | null; limit_from_free_credits?: boolean }
    | null
    | undefined

// The free credits stop a free-only scanner when it has no limit of its own, or when they leave less room than it.
export function stoppedByFreeCredits(scanner: LimitFields): boolean {
    return !!scanner?.free_only && (scanner.credit_limit == null || !!scanner.limit_from_free_credits)
}

export const FREE_CREDITS_STOPPED = 'Your free credits are used up, so this scanner stopped scanning.'

const FREE_CREDITS_USED_TOOLTIP = `${FREE_CREDITS_STOPPED} To keep scanning, turn off "Free credits only".`

export function limitReachedTooltip(scanner: LimitFields): string {
    return stoppedByFreeCredits(scanner) ? FREE_CREDITS_USED_TOOLTIP : LIMIT_REACHED_TOOLTIP
}

const DISABLED_REASON_DETAIL: Record<ScannerOffReason, string> = {
    manual: 'Someone turned this scanner off.',
    free_credits_used: 'Your free credits ran out.',
    no_ai_consent: "Your organization hasn't allowed AI analysis of recordings.",
    creator_lost_access:
        "Its creator left the organization or lost access to this project's recordings, and it scans as its creator. Turn it on to take it over and scan as you.",
    experiment_deleted: 'Its experiment was deleted.',
}

// Null when it was created off, or turned off before reasons were recorded.
export function disabledReasonDetail(reason: ScannerOffReason | null): string {
    return reason ? DISABLED_REASON_DETAIL[reason] : "This scanner doesn't scan new recordings."
}
