// Port of desktop `packages/shared/src/dismissal-reasons.ts`. Canonical reason codes recorded when a
// report is dismissed or resolved. Values are persisted on dismissal artefacts by the backend `state`
// action – add or reorder options here only, and keep the values in sync with desktop and with
// `SIGNAL_REPORT_DISMISSAL_REASON_CHOICES` in `products/signals/backend/views.py`.

export const DISMISSAL_REASON_OPTIONS = [
    { value: 'already_fixed', label: 'Already fixed' },
    { value: 'report_unclear', label: 'Report is unclear to me' },
    { value: 'analysis_wrong', label: "Agent's analysis is wrong" },
    { value: 'wrong_repo', label: 'Agent picked the wrong repository' },
    { value: 'wontfix_intentional', label: "Won't fix - intentional behavior" },
    { value: 'wontfix_irrelevant', label: "Won't fix - issue is real but insignificant" },
    { value: 'other', label: 'Something else…' },
] as const

/**
 * Reasons offered when a person resolves a report. `already_fixed` is also a dismiss reason on
 * purpose: as a dismissal it tells the agent the report was stale when filed, and as a resolve it
 * records the report as done. The person picks by which of those they want.
 */
export const RESOLVE_REASON_OPTIONS = [
    { value: 'fixed_outside_posthog', label: 'Fixed outside PostHog' },
    { value: 'pr_merged', label: 'PR was merged' },
    { value: 'already_fixed', label: 'Was already fixed before this report' },
    { value: 'other', label: 'Something else…' },
] as const

/** Persisted dismiss reason (values match {@link DISMISSAL_REASON_OPTIONS}). */
export type DismissalReasonValue = (typeof DISMISSAL_REASON_OPTIONS)[number]['value']

/** Persisted resolve reason (values match {@link RESOLVE_REASON_OPTIONS}). */
export type ResolveReasonValue = (typeof RESOLVE_REASON_OPTIONS)[number]['value']

/**
 * Whether a persisted reason describes a resolve rather than a dismissal. A resolved row only shows
 * a reason chip for these: a report that was dismissed, restored, then resolved by a merged PR keeps
 * its old dismiss reason, and showing that on finished work would mislabel it.
 */
export function isResolveReason(value: string | null | undefined): boolean {
    return value === 'fixed_outside_posthog' || value === 'pr_merged' || value === 'already_fixed'
}

/** Feedback captured by the dismiss dialog and forwarded to the report state API. */
export interface DismissalFeedback {
    reason: DismissalReasonValue
    note: string
    /** 'owner/repo' the reports should have targeted; only set when reason is 'wrong_repo'. */
    correctedRepository: string | null
}

/**
 * The dismissal fields of a `state`/`bulk-state` request body, so every surface maps
 * {@link DismissalFeedback} to the API the same way. Spread into `{ state: 'suppressed', ... }`.
 * The note is clamped to the API's 4000-character cap.
 */
export function suppressDismissalPayload(dismissal: DismissalFeedback): {
    dismissal_reason: DismissalReasonValue
    dismissal_note?: string
    corrected_repository?: string
} {
    const note = dismissal.note.trim().slice(0, 4000)
    return {
        dismissal_reason: dismissal.reason,
        ...(note ? { dismissal_note: note } : {}),
        // The API rejects corrected_repository with any other reason, so the gate lives here
        // rather than in every dialog that builds a DismissalFeedback.
        ...(dismissal.reason === 'wrong_repo' && dismissal.correctedRepository
            ? { corrected_repository: dismissal.correctedRepository }
            : {}),
    }
}

// Reason codes persisted by flows outside the two dialogs (never user-selectable there), so the
// reason chip still renders a label instead of the raw code. `refunded` is written by the PR
// refund action, which dismisses the report as part of the refund.
const EXTRA_DISMISSAL_REASON_LABELS: Record<string, string> = {
    refunded: 'Refunded',
}

/** Human label for a persisted reason code, or the raw code if it's not a known option. */
export function dismissalReasonLabel(value: string | null | undefined): string | null {
    if (!value) {
        return null
    }
    return (
        DISMISSAL_REASON_OPTIONS.find((o) => o.value === value)?.label ??
        RESOLVE_REASON_OPTIONS.find((o) => o.value === value)?.label ??
        EXTRA_DISMISSAL_REASON_LABELS[value] ??
        value
    )
}
