import { useState } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { captureInboxReportAction, InboxReportActionSurface } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import { hasOpenImplementationPr } from '../../utils/reportActions'
import { openResolveReportDialog } from '../shell/ResolveReportDialog'

/**
 * Resolve handler for the report detail pane: opens the resolve dialog, then marks the report done
 * through the `state` API. The single-report `resolve` analytics fire here so every detail surface
 * reads the same.
 */
export function useReportResolve({
    report,
    surface,
    onResolved,
}: {
    report: SignalReport
    /** Which surface the resolve was triggered from, for the `resolve` analytics. */
    surface: InboxReportActionSurface
    /** Fired once the resolve persists. */
    onResolved?: () => void
}): { isResolving: boolean; onResolveClick: (event: React.MouseEvent) => void } {
    const [isResolving, setIsResolving] = useState(false)
    // The backend closes an open implementation PR on resolve; the dialog and the toast say so.
    const hasOpenPr = hasOpenImplementationPr(report)

    const onResolveClick = (event: React.MouseEvent): void => {
        event.preventDefault()
        event.stopPropagation()
        openResolveReportDialog({
            reportTitle: report.title ?? 'Untitled report',
            hasOpenPr,
            onConfirm: async ({ reason, note }) => {
                // pinned: `dismissal_reason` is the persisted field the reason lands in, for both
                // verdicts, so one breakdown reads dismissals and resolves alike.
                // Only the structured reason — the free-form note can carry proprietary text, and the
                // state API below already stores it. Matches the bulk resolve path.
                captureInboxReportAction({
                    report,
                    actionType: 'resolve',
                    surface,
                    extra: { dismissal_reason: reason },
                })
                setIsResolving(true)
                try {
                    await api.signalReports.setState(report.id, {
                        state: 'resolved',
                        dismissal_reason: reason,
                        ...(note ? { dismissal_note: note } : {}),
                    })
                    lemonToast.success(hasOpenPr ? 'Report resolved. Closing its pull request.' : 'Report resolved')
                    onResolved?.()
                } catch (error: any) {
                    lemonToast.error(error?.detail || error?.message || 'Failed to resolve report')
                    // Reject so LemonDialog keeps the dialog open (the chosen reason and note survive
                    // for a retry) and captures genuine failures. Matches useReportRefund.
                    throw error
                } finally {
                    setIsResolving(false)
                }
            },
        })
    }

    return { isResolving, onResolveClick }
}
