// Port of desktop `packages/shared/src/dismissal-reasons.ts`. Canonical dismiss /
// suppress reasons shown in the inbox. Values are persisted on dismissal artefacts
// by the backend `state` action – add or reorder options here only, and keep the
// values in sync with desktop.

export const DISMISSAL_REASON_OPTIONS = [
    {
        value: 'already_fixed',
        label: 'Already fixed',
        snoozesInsteadOfDismiss: true,
    },
    {
        value: 'report_unclear',
        label: 'Report is unclear to me',
    },
    {
        value: 'analysis_wrong',
        label: "Agent's analysis is wrong",
    },
    {
        value: 'wrong_repo',
        label: 'Agent picked the wrong repository',
    },
    {
        value: 'wontfix_intentional',
        label: "Won't fix - intentional behavior",
    },
    {
        value: 'wontfix_irrelevant',
        label: "Won't fix - issue is real but insignificant",
    },
    { value: 'other', label: 'Something else…' },
] as const

/** Persisted dismissal / suppress reason (values match {@link DISMISSAL_REASON_OPTIONS}). */
export type DismissalReasonValue = (typeof DISMISSAL_REASON_OPTIONS)[number]['value']

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

// Reason codes persisted by flows outside the dismiss dialog (never user-selectable there), so the
// dismissal chip still renders a label instead of the raw code. `refunded` is written by the PR
// refund action, which archives the report as part of the refund.
const EXTRA_DISMISSAL_REASON_LABELS: Record<string, string> = {
    refunded: 'Refunded',
}

/** Whether the given reason snoozes the report (temporarily) instead of permanently dismissing it. */
export function isDismissalReasonSnooze(value: DismissalReasonValue): boolean {
    const option = DISMISSAL_REASON_OPTIONS.find((o) => o.value === value)
    return option != null && 'snoozesInsteadOfDismiss' in option && option.snoozesInsteadOfDismiss === true
}

/** Human label for a persisted dismissal reason code, or the raw code if it's not a known option. */
export function dismissalReasonLabel(value: string | null | undefined): string | null {
    if (!value) {
        return null
    }
    return (
        DISMISSAL_REASON_OPTIONS.find((o) => o.value === value)?.label ?? EXTRA_DISMISSAL_REASON_LABELS[value] ?? value
    )
}
