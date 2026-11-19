// Copied from `products/signals/frontend/inbox/utils/dismissalReasons.ts`. The backend persists these values, so keep
// them in sync with that file and with `SIGNAL_REPORT_DISMISSAL_REASON_CHOICES` in `products/signals/backend/views.py`.

export const DISMISSAL_REASON_OPTIONS = [
    { value: 'already_fixed', label: 'Already fixed' },
    { value: 'report_unclear', label: 'Report is unclear to me' },
    { value: 'analysis_wrong', label: "Agent's analysis is wrong" },
    { value: 'wrong_repo', label: 'Agent picked the wrong repository' },
    { value: 'wontfix_intentional', label: "Won't fix - intentional behavior" },
    { value: 'wontfix_irrelevant', label: "Won't fix - issue is real but insignificant" },
    { value: 'other', label: 'Something else…' },
] as const

export const RESOLVE_REASON_OPTIONS = [
    { value: 'fixed_outside_posthog', label: 'Fixed outside PostHog' },
    { value: 'pr_merged', label: 'PR was merged' },
    { value: 'already_fixed', label: 'Was already fixed before this report' },
    { value: 'other', label: 'Something else…' },
] as const

export type DismissReason = (typeof DISMISSAL_REASON_OPTIONS)[number]['value']
export type ResolveReason = (typeof RESOLVE_REASON_OPTIONS)[number]['value']

/** The state API caps `dismissal_note` at this many characters. */
export const VERDICT_NOTE_MAX_LENGTH = 4000
