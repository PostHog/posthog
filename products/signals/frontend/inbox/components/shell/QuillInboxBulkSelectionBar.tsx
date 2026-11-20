import '../tabs/QuillInboxList.scss'

import { useActions, useValues } from 'kea'

import { IconEllipsis, IconX } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Text,
} from '@posthog/quill'

import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { SignalReport } from '../../types'
import { reviewerRemovalReasonOptions } from '../../utils/reviewerRemovalReasons'
import { openDismissReportDialog } from './DismissReportDialog'
import { openResolveReportDialog } from './ResolveReportDialog'
import { useInboxBulkSelection } from './useInboxBulkSelection'

/** The Quill bar for the selected rows: Claim, Resolve and Dismiss, with Remove yourself in the menu. */
export function QuillInboxBulkSelectionBar({ reports }: { reports: SignalReport[] }): JSX.Element | null {
    const { isClaiming, isDismissing, isResolving, isUnassigning } = useValues(inboxBulkActionsLogic)
    const { clearSelection, bulkClaim, bulkDismiss, bulkResolve, bulkUnassignMe } = useActions(inboxBulkActionsLogic)
    const { selectedCount, busy, isMonitoring, hasOpenPr, unassignableIds, claimableIds } =
        useInboxBulkSelection(reports)

    if (selectedCount === 0) {
        return null
    }
    const working = busy ? 'Working…' : undefined

    return (
        <div className="QuillInboxBulkBar" data-quill-inverted data-attr="inbox-bulk-bar">
            <Text size="sm" weight="medium" render={<span />} className="me-2 whitespace-nowrap" translate="no">
                {`${selectedCount} selected`}
            </Text>
            <Button
                variant="outline"
                loading={isClaiming}
                disabledReason={
                    working ?? (claimableIds.length === 0 ? 'None of the selected reports can be claimed' : undefined)
                }
                onClick={() => bulkClaim(claimableIds)}
                data-attr="inbox-bulk-claim"
            >
                Claim
            </Button>
            <Button
                variant="outline"
                loading={isResolving}
                disabledReason={working}
                onClick={() =>
                    openResolveReportDialog({
                        selectedCount,
                        hasOpenPr,
                        isMonitoring,
                        onConfirm: ({ reason, note }) => bulkResolve(reason, note),
                    })
                }
                data-attr="inbox-bulk-resolve"
            >
                Resolve
            </Button>
            <Button
                variant="outline"
                loading={isDismissing}
                disabledReason={working}
                onClick={() =>
                    openDismissReportDialog({
                        selectedCount,
                        hasOpenPr,
                        onConfirm: (dismissal) => bulkDismiss(dismissal),
                    })
                }
                data-attr="inbox-bulk-dismiss"
            >
                Dismiss
            </Button>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            size="icon"
                            aria-label="More actions"
                            tooltip="More actions"
                            loading={isUnassigning}
                            data-attr="inbox-bulk-more"
                        />
                    }
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" side="top">
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Remove yourself</DropdownMenuLabel>
                        {reviewerRemovalReasonOptions(true).map((option) => (
                            <DropdownMenuItem
                                key={option.value}
                                disabledReason={
                                    working ??
                                    (unassignableIds.length === 0
                                        ? "You're not a reviewer on any selected report"
                                        : undefined)
                                }
                                onClick={() => bulkUnassignMe(unassignableIds, option.value)}
                                data-attr="inbox-bulk-unassign-me"
                            >
                                {option.label}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                        disabledReason={
                            working ??
                            (unassignableIds.length === 0 ? "You're not a reviewer on any selected report" : undefined)
                        }
                        onClick={() => bulkUnassignMe(unassignableIds)}
                        data-attr="inbox-bulk-unassign-me"
                    >
                        Without a reason
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            <Button
                size="icon"
                aria-label="Clear selection"
                tooltip="Clear selection (Esc)"
                onClick={() => clearSelection()}
                data-attr="inbox-bulk-clear"
            >
                <IconX />
            </Button>
        </div>
    )
}
