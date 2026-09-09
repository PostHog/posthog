import { useState } from 'react'

import api from 'lib/api'

import { captureInboxReportAction, InboxReportActionSurface } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import { DismissalFeedback, suppressDismissalPayload } from '../../utils/dismissalReasons'
import { openDismissReportDialog } from '../shell/DismissReportDialog'

/**
 * Shared dismiss handler for the inbox cards and the detail pane. Opens the dismiss dialog and
 * either delegates to the bound list logic via `onDismiss` (optimistic) or, when used standalone
 * (e.g. stories), falls back to a direct `signalReports.setState` call. The single-report
 * `dismiss` analytics fire here so both the list card and the detail pane are covered from one
 * place.
 */
export function useReportDismiss({
    reportId,
    cardTitle,
    report,
    surface,
    onDismiss,
    onDismissed,
}: {
    reportId: string
    cardTitle: string
    /** The report being dismissed, used to enrich the `dismiss` analytics. */
    report?: SignalReport | null
    /** Which surface the dismiss was triggered from, for the `dismiss` analytics. */
    surface?: InboxReportActionSurface
    onDismiss?: (dismissal: DismissalFeedback) => void
    /** Fired once the report is dismissed (after `onDismiss`, or after the fallback API call succeeds). */
    onDismissed?: () => void
}): { isDismissing: boolean; onDismissClick: (event: React.MouseEvent) => void } {
    const [isDismissing, setIsDismissing] = useState(false)

    const onDismissClick = (event: React.MouseEvent): void => {
        event.preventDefault()
        event.stopPropagation()
        openDismissReportDialog({
            reportTitle: cardTitle,
            onConfirm: async (dismissal) => {
                const { reason, note, correctedRepository } = dismissal
                // The structured reason plus the user's note — the note is the actionable signal
                // we want for tuning the agent, so it rides along with the dismiss event.
                captureInboxReportAction({
                    report: report ?? null,
                    actionType: 'dismiss',
                    surface: surface ?? 'list_row',
                    extra: {
                        dismissal_reason: reason,
                        ...(note ? { dismissal_note: note } : {}),
                        ...(correctedRepository ? { dismissal_corrected_repository: correctedRepository } : {}),
                    },
                })
                if (onDismiss) {
                    onDismiss(dismissal)
                    onDismissed?.()
                    return
                }
                // Fallback for standalone usage (e.g. stories) without a bound list logic.
                setIsDismissing(true)
                try {
                    await api.signalReports.setState(reportId, {
                        state: 'suppressed',
                        ...suppressDismissalPayload(dismissal),
                    })
                    onDismissed?.()
                } finally {
                    setIsDismissing(false)
                }
            },
        })
    }

    return { isDismissing, onDismissClick }
}
