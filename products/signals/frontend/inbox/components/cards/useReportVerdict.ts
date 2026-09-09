import { useActions } from 'kea'

import { captureInboxReportAction, InboxReportActionSurface } from '../../inboxAnalytics'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { InboxReportSectionKey, SignalReport } from '../../types'
import { DismissalFeedback, DismissalReasonValue, ResolveReasonValue } from '../../utils/dismissalReasons'
import { hasOpenImplementationPr } from '../../utils/reportActions'
import { displayConventionalCommitTitle } from '../../utils/reportPresentation'
import { openDismissReportDialog } from '../shell/DismissReportDialog'
import { openResolveReportDialog } from '../shell/ResolveReportDialog'

export interface ReportVerdict {
    /** Dismiss with this reason now, or open the dialog for the reasons that need more than a click. */
    pickDismissReason: (reason: DismissalReasonValue) => void
    /** Resolve with this reason now, or open the dialog when the report has an open PR to close. */
    pickResolveReason: (reason: ResolveReasonValue) => void
    /** Open the dismiss dialog with the reason preselected, for the note the instant path skips. */
    openDismissDialog: (initialReason?: DismissalReasonValue) => void
    /** Open the resolve dialog with the reason preselected, for the note the instant path skips. */
    openResolveDialog: (initialReason?: ResolveReasonValue) => void
}

/**
 * The dismiss and resolve verdicts for one report row, shared by the row's verdict buttons and the
 * right-click menu so the two cannot drift apart. Picking a reason applies it immediately through
 * the owning section's list logic; the dialog is reserved for the reasons that need more than a
 * click. A report with an open implementation PR always goes through it, because resolving or
 * dismissing closes that PR and the dialog's warning and confirm step stand in for the instant
 * apply. A wrong-repo dismissal goes through it too, so the person can name the repository the
 * report should have targeted.
 */
export function useReportVerdict({
    report,
    sectionKey,
    surface,
    onOpenDialog,
}: {
    report: SignalReport
    /** The list state that owns the row; its keyed logic applies the optimistic update. */
    sectionKey: InboxReportSectionKey
    /** Which surface the verdict was reached from, for the `dismiss` / `resolve` analytics. */
    surface: InboxReportActionSurface
    /** Called just before a dialog opens, for surfaces that have to step out of the way of it. */
    onOpenDialog?: () => void
}): ReportVerdict {
    const { dismissReport, resolveReport } = useActions(reportListLogic(sectionListLogicProps(sectionKey)))

    const reportTitle = displayConventionalCommitTitle(report.title, 'Untitled report')
    const hasOpenPr = hasOpenImplementationPr(report)

    const dismissWith = (dismissal: DismissalFeedback): void => {
        const { reason, note, correctedRepository } = dismissal
        // The structured reason plus the user's note — the note is the actionable signal we want for
        // tuning the agent, so it rides along with the dismiss event.
        captureInboxReportAction({
            report,
            actionType: 'dismiss',
            surface,
            extra: {
                dismissal_reason: reason,
                ...(note ? { dismissal_note: note } : {}),
                ...(correctedRepository ? { dismissal_corrected_repository: correctedRepository } : {}),
            },
        })
        dismissReport(report.id, dismissal)
    }

    const resolveWith = (reason: ResolveReasonValue, note: string): void => {
        // pinned: `dismissal_reason` is the persisted field the reason lands in, for both verdicts.
        // Only the structured reason — the free-form note can carry proprietary text.
        captureInboxReportAction({
            report,
            actionType: 'resolve',
            surface,
            extra: { dismissal_reason: reason },
        })
        resolveReport(report.id, reason, note)
    }

    const openDismissDialog = (initialReason?: DismissalReasonValue): void => {
        onOpenDialog?.()
        openDismissReportDialog({ reportTitle, hasOpenPr, initialReason, onConfirm: dismissWith })
    }

    const openResolveDialog = (initialReason?: ResolveReasonValue): void => {
        onOpenDialog?.()
        openResolveReportDialog({
            reportTitle,
            hasOpenPr,
            initialReason,
            onConfirm: ({ reason, note }) => resolveWith(reason, note),
        })
    }

    return {
        pickDismissReason: (reason) => {
            if (reason === 'wrong_repo' || hasOpenPr) {
                openDismissDialog(reason)
                return
            }
            dismissWith({ reason, note: '', correctedRepository: null })
        },
        pickResolveReason: (reason) => {
            if (hasOpenPr) {
                openResolveDialog(reason)
                return
            }
            resolveWith(reason, '')
        },
        openDismissDialog,
        openResolveDialog,
    }
}
