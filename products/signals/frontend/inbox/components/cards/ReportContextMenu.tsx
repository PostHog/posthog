import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode, useRef } from 'react'

import {
    IconArrowUpRight,
    IconCheckbox,
    IconCheckCircle,
    IconChevronRight,
    IconCopy,
    IconExternal,
    IconHide,
    IconLeave,
    IconPeople,
    IconPerson,
    IconPullRequest,
    IconUndo,
} from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { fullNameOrEmail } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { reportGithubAccessLogic } from '../../logics/reportGithubAccessLogic'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { InboxReportSectionKey, SignalReport, SignalReportStatus } from '../../types'
import {
    DISMISSAL_REASON_OPTIONS,
    DismissalFeedback,
    DismissalReasonValue,
    RESOLVE_REASON_OPTIONS,
    STOP_MONITORING_REASON_OPTIONS,
    ResolveReasonValue,
} from '../../utils/dismissalReasons'
import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import {
    canCreateImplementationPr,
    canResolveReport,
    canUnassignMe,
    hasOpenImplementationPr,
} from '../../utils/reportActions'
import { isReportClaimable, reportClaimant } from '../../utils/reportClaim'
import { displayConventionalCommitTitle } from '../../utils/reportPresentation'
import { reviewerRemovalReasonOptions } from '../../utils/reviewerRemovalReasons'
import { ReviewerSearchList } from '../detail/ReviewerSearchList'
import { openDismissReportDialog } from '../shell/DismissReportDialog'
import { openResolveReportDialog } from '../shell/ResolveReportDialog'
import { ReasonSubmenuItems } from './ReasonSubmenuItems'
import { useReportCardSelection } from './useReportCardSelection'

/**
 * Right-click menu on a report row in the flat inbox list: the report's major actions without
 * opening its detail. Claim, Create PR, Resolve, Dismiss, and Reviewers follow the same eligibility rules
 * as the detail pane (`utils/reportActions.ts`); a dismissed row offers Restore instead. Resolve
 * and Dismiss nest their canonical reasons, and picking one applies immediately through the owning
 * section's list logic. The dialog stays available for a note, a corrected repository, or an open
 * implementation PR warning. Rows with no action (resolved, refunded) render without a menu, so
 * the browser's own menu still works there. On rows with a menu the trigger suppresses that native
 * menu over the row's link, so the standard link actions return as an explicit section at the
 * bottom (open, open in new tab, copy link).
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
    // Set when a menu item opens a dialog, read once when the menu closes right after.
    const openedDialogRef = useRef(false)

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
            <ContextMenuContent
                loop
                className="min-w-48"
                // The verdict dialogs autofocus their first field, and the menu closes on the same
                // click. Its closing focus restore runs after the dialog opens and would
                // pull focus back to the row, so skip the restore for exactly that close.
                onCloseAutoFocus={(event) => {
                    if (openedDialogRef.current) {
                        openedDialogRef.current = false
                        event.preventDefault()
                    }
                }}
            >
                <ReportContextMenuItems
                    report={report}
                    sectionKey={sectionKey}
                    isDismissed={isDismissed}
                    onOpenDialog={() => (openedDialogRef.current = true)}
                />
            </ContextMenuContent>
        </ContextMenu>
    )
}

/** The open menu's items. Mounted only while the menu is open. */
function ReportContextMenuItems({
    report,
    sectionKey,
    isDismissed,
    onOpenDialog,
}: {
    report: SignalReport
    sectionKey: InboxReportSectionKey
    isDismissed: boolean
    /** Tells the menu a dialog is opening, so its close skips the focus restore. */
    onOpenDialog: () => void
}): JSX.Element {
    const { dismissReport, resolveReport, restoreReport, setReportClaimed, unassignMe } = useActions(
        reportListLogic(sectionListLogicProps(sectionKey))
    )
    const { isScopedToMe } = useValues(inboxFiltersLogic)
    const { claimSavingReportIds } = useValues(reportListLogic(sectionListLogicProps(sectionKey)))
    const { user } = useValues(userLogic)
    // Kept mounted by `ReportsTab` beyond this menu's lifetime, so the create-PR listener survives
    // the menu closing on click.
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const { createPrDisabledReason: globalPrDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { disabledReason: githubDisabledReason } = useValues(reportGithubAccessLogic({ report }))
    const createPrDisabledReason = globalPrDisabledReason ?? githubDisabledReason
    const reportTitle = displayConventionalCommitTitle(report.title, 'Untitled report')
    const hasOpenPr = hasOpenImplementationPr(report)
    const { isSelected, toggle: toggleSelection } = useReportCardSelection(report.id, true)

    // The row's own selection gestures (hold, Shift-click) are easy to miss, so the menu names
    // the feature outright.
    const selectItem = (
        <ContextMenuItem asChild>
            <ButtonPrimitive
                menuItem
                onClick={() => toggleSelection('context_menu')}
                data-attr="inbox-report-context-menu-select"
            >
                <IconCheckbox />
                {isSelected ? 'Deselect' : 'Select'}
            </ButtonPrimitive>
        </ContextMenuItem>
    )

    // A teammate's claim shows disabled with their name, so the menu says why it can't be taken.
    const claimant = reportClaimant(report)
    const isMyClaim = !!claimant && !!user?.uuid && claimant.uuid === user.uuid
    const claimDisabledReason = claimSavingReportIds.includes(report.id)
        ? 'Updating…'
        : claimant && !isMyClaim
          ? `${fullNameOrEmail(claimant)} is working on this report`
          : null
    const claimItem =
        claimant || isReportClaimable(report) ? (
            <ContextMenuItem asChild disabled={!!claimDisabledReason}>
                <ButtonPrimitive
                    menuItem
                    onClick={() => setReportClaimed(report, !isMyClaim, 'context_menu')}
                    disabledReasons={claimDisabledReason ? { [claimDisabledReason]: true } : undefined}
                    data-attr={isMyClaim ? 'inbox-report-context-menu-unclaim' : 'inbox-report-context-menu-claim'}
                >
                    <IconPerson />
                    {isMyClaim ? 'Unclaim' : 'Claim'}
                </ButtonPrimitive>
            </ContextMenuItem>
        ) : null

    const dismissWith = (dismissal: DismissalFeedback): void => {
        const { reason, note, correctedRepository } = dismissal
        captureInboxReportAction({
            report,
            actionType: 'dismiss',
            surface: 'context_menu',
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
        // Only the structured reason is safe for analytics because the note can contain private text.
        captureInboxReportAction({
            report,
            actionType: 'resolve',
            surface: 'context_menu',
            extra: { dismissal_reason: reason },
        })
        resolveReport(report.id, reason, note)
    }

    const openDismissDialog = (initialReason?: DismissalReasonValue): void => {
        onOpenDialog()
        openDismissReportDialog({ reportTitle, hasOpenPr, initialReason, onConfirm: dismissWith })
    }

    const openResolveDialog = (initialReason?: ResolveReasonValue): void => {
        onOpenDialog()
        openResolveReportDialog({
            reportTitle,
            hasOpenPr,
            isMonitoring: report.status === SignalReportStatus.MONITORING,
            initialReason,
            onConfirm: ({ reason, note }) => resolveWith(reason, note),
        })
    }

    const pickDismissReason = (reason: DismissalReasonValue): void => {
        if (reason === 'wrong_repo' || hasOpenPr) {
            openDismissDialog(reason)
            return
        }
        dismissWith({ reason, note: '', correctedRepository: null })
    }

    const pickResolveReason = (reason: ResolveReasonValue): void => {
        if (hasOpenPr) {
            openResolveDialog(reason)
            return
        }
        resolveWith(reason, '')
    }

    // The menu only mounts in the flat Reports list, whose rows link to the reports tab with no
    // back param, so the default detail URL is exactly the row's own href.
    const detailUrl = inboxReportDetailUrl(report.id)

    // The trigger swallows the browser's native context menu over the row's link (a Radix
    // behavior), so the link actions a person expects there come back as menu items.
    const browserLinkItems = (
        <>
            {/* This separator sits outside a padded menu group. Its default negative margin sets
                horizontal overflow on ScrollableShadows and adds a shadow to the menu's right edge. */}
            <ContextMenuSeparator className="mx-0" />
            <ContextMenuGroup>
                <ContextMenuItem asChild>
                    <ButtonPrimitive
                        menuItem
                        onClick={() => router.actions.push(detailUrl)}
                        data-attr="inbox-report-context-menu-open-link"
                    >
                        <IconArrowUpRight />
                        Open link
                    </ButtonPrimitive>
                </ContextMenuItem>
                <ContextMenuItem asChild>
                    <ButtonPrimitive
                        menuItem
                        onClick={() => window.open(detailUrl, '_blank')}
                        data-attr="inbox-report-context-menu-open-link-new-tab"
                    >
                        <IconExternal />
                        Open link in new tab
                    </ButtonPrimitive>
                </ContextMenuItem>
                <ContextMenuItem asChild>
                    <ButtonPrimitive
                        menuItem
                        onClick={() => void copyToClipboard(window.location.origin + detailUrl, 'link')}
                        data-attr="inbox-report-context-menu-copy-link"
                    >
                        <IconCopy />
                        Copy link
                    </ButtonPrimitive>
                </ContextMenuItem>
            </ContextMenuGroup>
        </>
    )

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
            <>
                <ContextMenuGroup>
                    {selectItem}
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
                {browserLinkItems}
            </>
        )
    }

    return (
        <>
            <ContextMenuGroup>
                {selectItem}
                {claimItem}
                {canCreateImplementationPr(report) && (
                    <>
                        <ContextMenuItem asChild disabled={!!createPrDisabledReason}>
                            <ButtonPrimitive
                                menuItem
                                onClick={onCreatePr}
                                disabledReasons={
                                    createPrDisabledReason ? { [createPrDisabledReason]: true } : undefined
                                }
                                data-attr="inbox-report-context-menu-create-pr"
                            >
                                <IconPullRequest />
                                Create PR
                            </ButtonPrimitive>
                        </ContextMenuItem>
                        {/* Create PR acts on its own; the divider separates it from the verdict submenus. */}
                        <ContextMenuSeparator />
                    </>
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
                            <ReasonSubmenuItems
                                options={
                                    report.status === SignalReportStatus.MONITORING
                                        ? STOP_MONITORING_REASON_OPTIONS
                                        : RESOLVE_REASON_OPTIONS
                                }
                                noteTooltip="Resolve and write a note"
                                dataAttrPrefix="inbox-report-context-menu-resolve"
                                onPick={pickResolveReason}
                                onPickWithNote={openResolveDialog}
                            />
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
                        <ReasonSubmenuItems
                            options={DISMISSAL_REASON_OPTIONS}
                            noteTooltip="Dismiss and write a note"
                            dataAttrPrefix="inbox-report-context-menu-dismiss"
                            onPick={pickDismissReason}
                            onPickWithNote={openDismissDialog}
                        />
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
                {/* The picker removes without a reason, so the common case of stepping off gets its own
                reasons, matching the reviewer menu in the detail pane. */}
                {canUnassignMe(report, isScopedToMe) && (
                    <ContextMenuSub>
                        <ContextMenuSubTrigger asChild data-attr="inbox-report-context-menu-remove-yourself">
                            <ButtonPrimitive menuItem>
                                <IconLeave />
                                Remove yourself
                                <IconChevronRight className="ml-auto size-3" />
                            </ButtonPrimitive>
                        </ContextMenuSubTrigger>
                        <ContextMenuSubContent className="max-w-80">
                            <ContextMenuGroup>
                                {reviewerRemovalReasonOptions(true).map((option) => (
                                    <ContextMenuItem asChild key={option.value}>
                                        <ButtonPrimitive
                                            menuItem
                                            onClick={() => unassignMe(report.id, 'context_menu', option.value)}
                                            data-attr="inbox-report-context-menu-remove-yourself-reason"
                                        >
                                            {option.label}
                                        </ButtonPrimitive>
                                    </ContextMenuItem>
                                ))}
                                <ContextMenuSeparator />
                                <ContextMenuItem asChild>
                                    <ButtonPrimitive
                                        menuItem
                                        onClick={() => unassignMe(report.id, 'context_menu')}
                                        data-attr="inbox-report-context-menu-remove-yourself-no-reason"
                                    >
                                        Without a reason
                                    </ButtonPrimitive>
                                </ContextMenuItem>
                            </ContextMenuGroup>
                        </ContextMenuSubContent>
                    </ContextMenuSub>
                )}
            </ContextMenuGroup>
            {browserLinkItems}
        </>
    )
}
