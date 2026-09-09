import { useActions } from 'kea'
import { router } from 'kea-router'
import { Fragment, ReactNode, useRef } from 'react'

import {
    IconArrowUpRight,
    IconCheckCircle,
    IconChevronRight,
    IconCopy,
    IconExternal,
    IconHide,
    IconPeople,
    IconPencil,
    IconPullRequest,
    IconUndo,
} from '@posthog/icons'

import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
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

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { InboxReportSectionKey, SignalReport, SignalReportStatus } from '../../types'
import {
    DISMISSAL_REASON_OPTIONS,
    DismissalFeedback,
    DismissalReasonValue,
    RESOLVE_REASON_OPTIONS,
    ResolveReasonValue,
} from '../../utils/dismissalReasons'
import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
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

/**
 * One verdict's reasons inside its submenu. Every reason applies on click; "Something else…" sits
 * apart below them because its trailing pencil is the only way left to write a note, and Radix gives
 * an item one action, so the pencil is a focusable item of its own.
 */
function ReasonSubmenuItems<T extends string>({
    options,
    noteTooltip,
    dataAttrPrefix,
    onPick,
    onPickWithNote,
}: {
    options: readonly { readonly value: T; readonly label: string }[]
    noteTooltip: string
    dataAttrPrefix: string
    onPick: (reason: T) => void
    onPickWithNote: (reason: T) => void
}): JSX.Element {
    return (
        <ContextMenuGroup>
            {options.map((option) =>
                option.value === 'other' ? (
                    <Fragment key={option.value}>
                        <ContextMenuSeparator />
                        <ButtonGroupPrimitive fullWidth>
                            <ContextMenuItem asChild>
                                <ButtonPrimitive
                                    menuItem
                                    hasSideActionRight
                                    onClick={() => onPick(option.value)}
                                    data-attr={`${dataAttrPrefix}-reason`}
                                >
                                    {option.label}
                                </ButtonPrimitive>
                            </ContextMenuItem>
                            <ContextMenuItem asChild>
                                <ButtonPrimitive
                                    iconOnly
                                    isSideActionRight
                                    tooltip={noteTooltip}
                                    aria-label={noteTooltip}
                                    onClick={() => onPickWithNote(option.value)}
                                    data-attr={`${dataAttrPrefix}-note`}
                                >
                                    <IconPencil />
                                </ButtonPrimitive>
                            </ContextMenuItem>
                        </ButtonGroupPrimitive>
                    </Fragment>
                ) : (
                    <ContextMenuItem asChild key={option.value}>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => onPick(option.value)}
                            data-attr={`${dataAttrPrefix}-reason`}
                        >
                            {option.label}
                        </ButtonPrimitive>
                    </ContextMenuItem>
                )
            )}
        </ContextMenuGroup>
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
    const { dismissReport, resolveReport, restoreReport } = useActions(
        reportListLogic(sectionListLogicProps(sectionKey))
    )
    // Kept mounted by `ReportsTab` beyond this menu's lifetime, so the create-PR listener survives
    // the menu closing on click.
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const reportTitle = displayConventionalCommitTitle(report.title, 'Untitled report')
    const hasOpenPr = hasOpenImplementationPr(report)

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

    // The menu only mounts in the redesign flat list, whose rows link to the reports tab with no
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
                {canCreateImplementationPr(report) && (
                    <>
                        <ContextMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={onCreatePr}
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
                                options={RESOLVE_REASON_OPTIONS}
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
            </ContextMenuGroup>
            {browserLinkItems}
        </>
    )
}
