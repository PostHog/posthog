import { useActions } from 'kea'

import { IconCheckCircle, IconHide } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { InboxReportSectionKey, SignalReport, SignalReportStatus } from '../../types'
import { canResolveReport, hasOpenImplementationPr } from '../../utils/reportActions'
import { displayConventionalCommitTitle } from '../../utils/reportPresentation'
import { openDismissReportDialog } from '../shell/DismissReportDialog'
import { openResolveReportDialog } from '../shell/ResolveReportDialog'

/**
 * Resolve and Dismiss on a Home-style list row. They go through the owning section's list logic, as the
 * right-click menu does, so the row leaves the list at once.
 */
export function InboxTodayVerdictButtons({
    report,
    sectionKey,
    labelled = false,
}: {
    report: SignalReport
    sectionKey: InboxReportSectionKey
    labelled?: boolean
}): JSX.Element | null {
    const { dismissReport, resolveReport } = useActions(reportListLogic(sectionListLogicProps(sectionKey)))
    const canDismiss = report.status !== SignalReportStatus.SUPPRESSED && report.status !== SignalReportStatus.RESOLVED
    const canResolve = canResolveReport(report)
    if (!canDismiss && !canResolve) {
        return null
    }
    const reportTitle = displayConventionalCommitTitle(report.title, 'Untitled report')
    const hasOpenPr = hasOpenImplementationPr(report)

    const openResolve = (): void =>
        openResolveReportDialog({
            reportTitle,
            hasOpenPr,
            isMonitoring: report.status === SignalReportStatus.MONITORING,
            onConfirm: ({ reason, note }) => {
                // Only the structured reason is safe for analytics, because the note can contain private text.
                captureInboxReportAction({
                    report,
                    actionType: 'resolve',
                    surface: 'list_row',
                    extra: { dismissal_reason: reason },
                })
                resolveReport(report.id, reason, note)
            },
        })

    const openDismiss = (): void =>
        openDismissReportDialog({
            reportTitle,
            hasOpenPr,
            onConfirm: (dismissal) => {
                captureInboxReportAction({
                    report,
                    actionType: 'dismiss',
                    surface: 'list_row',
                    extra: { dismissal_reason: dismissal.reason },
                })
                dismissReport(report.id, dismissal)
            },
        })

    const buttons = [
        ...(canResolve
            ? [{ label: 'Resolve', icon: <IconCheckCircle className="size-3.5" />, onClick: openResolve }]
            : []),
        ...(canDismiss ? [{ label: 'Dismiss', icon: <IconHide className="size-3.5" />, onClick: openDismiss }] : []),
    ]

    return (
        <>
            {buttons.map(({ label, icon, onClick }) => (
                <Button
                    key={label}
                    variant="link-muted"
                    size={labelled ? 'sm' : 'icon-sm'}
                    aria-label={label}
                    tooltip={labelled ? undefined : label}
                    onClick={onClick}
                    data-attr={`inbox-today-row-${label.toLowerCase()}`}
                >
                    {icon}
                    {labelled && label}
                </Button>
            ))}
        </>
    )
}
