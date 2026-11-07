import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

export interface ReportCheckStopConfirmation {
    title: string
    description: string
    confirmLabel: string
    dismissLabel: string
}

/** The confirmation that `ReportCheckRow` and its quill sibling show before a check is canceled. */
export function reportCheckStopConfirmation(check: Pick<SignalReportCheckApi, 'title'>): ReportCheckStopConfirmation {
    return {
        title: 'Cancel this check?',
        description: `This cancels future runs of "${check.title}". Results it already recorded stay on this report.`,
        confirmLabel: 'Cancel this check',
        dismissLabel: 'Keep it',
    }
}
