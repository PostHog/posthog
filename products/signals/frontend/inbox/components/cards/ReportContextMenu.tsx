import { useActions } from 'kea'
import { ReactNode } from 'react'

import { IconCheckCircle, IconChevronRight, IconHide, IconPeople, IconPullRequest, IconUndo } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { InboxReportSectionKey, SignalReport, SignalReportStatus } from '../../types'
import {
    DISMISSAL_REASON_OPTIONS,
    DismissalReasonValue,
    RESOLVE_REASON_OPTIONS,
    ResolveReasonValue,
} from '../../utils/dismissalReasons'
import { canCreateImplementationPr, canResolveReport, hasOpenImplementationPr } from '../../utils/reportActions'
import { displayConventionalCommitTitle } from '../../utils/reportPresentation'
import { ReviewerSearchList } from '../detail/ReviewerSearchList'
import { openDismissReportDialog } from '../shell/DismissReportDialog'
import { openResolveReportDialog } from '../shell/ResolveReportDialog'

/**
 * Right-click menu on a report row in the flat inbox list: the report's major actions without
 * opening its detail. Create PR, Resolve, Dismiss, and Reviewers follow the same eligibility rules
 * as the detail pane (`utils/reportActions.ts`); a dismissed row offers Restore instead. Resolve
 * and Dismiss nest their canonical reasons, and picking one applies immediately through the owning
 * section's list logic, except "Something else…", which opens the existing dialog to collect the
 * note that reason needs. Rows with no action (resolved, refunded) render without a menu, so the
 * browser's own menu still works there.
 */
export function ReportContextMenu({
    report,
    sectionKey,
    children,
}: {
    report: SignalReport
    /** The list state that owns the row; its keyed logic applies the optimistic update. */
    sectionKey: InboxReportSectionKey
    children: ReactNode
}): JSX.Element {
    const isDismissed = report.status === SignalReportStatus.SUPPRESSED
    const isResolved = report.status === SignalReportStatus.RESOLVED

    // Resolved reports are terminal, and a refunded dismissed report cannot be restored.
    if (isResolved || (isDismissed && !!report.refund)) {
        return <>{children}</>
    }

    return (
        <ContextMenu>
            <ContextMenuTrigger asChild>
                {/* Plain wrapper: the card component doesn't forward the ref the trigger needs. */}
                <div className="flex min-w-0 flex-col">{children}</div>
            </ContextMenuTrigger>
            {/* The item tree lives in its own component so a closed row builds one element and
                mounts no logic; `ContextMenuContent` renders its children only while open. */}
            <ContextMenuContent loop className="min-w-48">
                <ReportContextMenuItems report={report} sectionKey={sectionKey} isDismissed={isDismissed} />
            </ContextMenuContent>
        </ContextMenu>
    )
}

/** The open menu's items. Mounted only while the menu is open. */
function ReportContextMenuItems({
    report,
    sectionKey,
    isDismissed,
}: {
    report: SignalReport
    sectionKey: InboxReportSectionKey
    isDismissed: boolean
}): JSX.Element {
    const { dismissReport, resolveReport, restoreReport } = useActions(
        reportListLogic(sectionListLogicProps(sectionKey))
    )
    // Kept mounted by `ReportsTab` beyond this menu's lifetime, so the create-PR listener survives
    // the menu closing on click.
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)

    const reportTitle = displayConventionalCommitTitle(report.title, 'Untitled report')

    const resolveWithReason = (reason: ResolveReasonValue, note: string): void => {
        // pinned: `dismissal_reason` is the persisted field the reason lands in, for both verdicts.
        // Only the structured reason — the free-form note can carry proprietary text.
        captureInboxReportAction({
            report,
            actionType: 'resolve',
            surface: 'context_menu',
            extra: { dismissal_reason: reason },
        })
        resolveReport(report.id, reason, note)
    }

    const dismissWithReason = (reason: DismissalReasonValue, note: string): void => {
        captureInboxReportAction({
            report,
            actionType: 'dismiss',
            surface: 'context_menu',
            extra: { dismissal_reason: reason, ...(note ? { dismissal_note: note } : {}) },
        })
        dismissReport(report.id, reason, note)
    }

    // "Something else…" needs the note the other reasons don't, so it goes through the dialog.
    const pickResolveReason = (reason: ResolveReasonValue): void => {
        if (reason === 'other') {
            openResolveReportDialog({
                reportTitle,
                hasOpenPr: hasOpenImplementationPr(report),
                initialReason: reason,
                onConfirm: ({ reason, note }) => resolveWithReason(reason, note),
            })
            return
        }
        resolveWithReason(reason, '')
    }

    const pickDismissReason = (reason: DismissalReasonValue): void => {
        if (reason === 'other') {
            openDismissReportDialog({
                reportTitle,
                initialReason: reason,
                onConfirm: ({ reason, note }) => dismissWithReason(reason, note),
            })
            return
        }
        dismissWithReason(reason, '')
    }

    const onCreatePr = (): void => {
        captureInboxReportAction({
            report,
            actionType: 'create_pr',
            surface: 'context_menu',
            extra: { has_feedback: false },
        })
        // Self-guards on AI consent (toast) and navigates to the created run.
        createPrFromReport(report)
    }

    if (isDismissed) {
        return (
            <ContextMenuGroup>
                <ContextMenuItem asChild>
                    <ButtonPrimitive
                        menuItem
                        onClick={() => restoreReport(report.id, 'context_menu')}
                        data-attr="inbox-report-context-menu-restore"
                    >
                        <IconUndo />
                        Restore
                    </ButtonPrimitive>
                </ContextMenuItem>
            </ContextMenuGroup>
        )
    }

    return (
        <ContextMenuGroup>
            {canCreateImplementationPr(report) && (
                <ContextMenuItem asChild>
                    <ButtonPrimitive menuItem onClick={onCreatePr} data-attr="inbox-report-context-menu-create-pr">
                        <IconPullRequest />
                        Create PR
                    </ButtonPrimitive>
                </ContextMenuItem>
            )}
            {canResolveReport(report) && (
                <ContextMenuSub>
                    <ContextMenuSubTrigger asChild data-attr="inbox-report-context-menu-resolve">
                        <ButtonPrimitive menuItem>
                            <IconCheckCircle />
                            Resolve
                            <IconChevronRight className="ml-auto size-3" />
                        </ButtonPrimitive>
                    </ContextMenuSubTrigger>
                    {/* The base menu caps at 200px, which wraps the longer reason labels into the
                        buttons' fixed height. */}
                    <ContextMenuSubContent className="max-w-80">
                        <ContextMenuGroup>
                            {RESOLVE_REASON_OPTIONS.map((option) => (
                                <ContextMenuItem key={option.value} asChild>
                                    <ButtonPrimitive
                                        menuItem
                                        onClick={() => pickResolveReason(option.value)}
                                        data-attr="inbox-report-context-menu-resolve-reason"
                                    >
                                        {option.label}
                                    </ButtonPrimitive>
                                </ContextMenuItem>
                            ))}
                        </ContextMenuGroup>
                    </ContextMenuSubContent>
                </ContextMenuSub>
            )}
            <ContextMenuSub>
                <ContextMenuSubTrigger asChild data-attr="inbox-report-context-menu-dismiss">
                    <ButtonPrimitive menuItem>
                        <IconHide />
                        Dismiss
                        <IconChevronRight className="ml-auto size-3" />
                    </ButtonPrimitive>
                </ContextMenuSubTrigger>
                <ContextMenuSubContent className="max-w-80">
                    <ContextMenuGroup>
                        {DISMISSAL_REASON_OPTIONS.map((option) => (
                            <ContextMenuItem key={option.value} asChild>
                                <ButtonPrimitive
                                    menuItem
                                    onClick={() => pickDismissReason(option.value)}
                                    data-attr="inbox-report-context-menu-dismiss-reason"
                                >
                                    {option.label}
                                </ButtonPrimitive>
                            </ContextMenuItem>
                        ))}
                    </ContextMenuGroup>
                </ContextMenuSubContent>
            </ContextMenuSub>
            <ContextMenuSub>
                <ContextMenuSubTrigger asChild data-attr="inbox-report-context-menu-reviewers">
                    <ButtonPrimitive menuItem>
                        <IconPeople />
                        Reviewers
                        <IconChevronRight className="ml-auto size-3" />
                    </ButtonPrimitive>
                </ContextMenuSubTrigger>
                {/* The picker sizes itself; the base menu's 200px cap would clip it. */}
                <ContextMenuSubContent className="max-w-none">
                    {/* Mounts the report detail logic on open, which loads the same reviewer
                        artefact and member search as the detail pane. */}
                    <ReviewerSearchList report={report} surface="context_menu" />
                </ContextMenuSubContent>
            </ContextMenuSub>
        </ContextMenuGroup>
    )
}
