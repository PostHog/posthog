import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { type MouseEvent, useState } from 'react'

import { IconCheckCircle, IconHide, IconReceipt, IconUndo } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { INBOX_REPORT_SECTION_LIST_PARAMS, reportListLogic } from '../../logics/reportListLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { canResolveReport } from '../../utils/reportActions'
import { useReportDismiss } from '../cards/useReportDismiss'
import { useReportRefund } from '../cards/useReportRefund'
import { useReportResolve } from './useReportResolve'

/**
 * One detail-pane action, rendered either inline as a `LemonButton` (wide layouts) or as a
 * `LemonMenu` item (the "…" overflow on narrow layouts). Keeping actions as data lets both
 * surfaces share a single source of truth instead of duplicating the button JSX.
 */
export interface ReportDetailAction {
    key: string
    label: string
    icon: JSX.Element
    onClick: (event: MouseEvent) => void
    loading?: boolean
    tooltip?: string
    /** Renders the action disabled with this explanation (e.g. a PR past its refund window). */
    disabledReason?: string
    /** Renders inline as the primary button: the one step the report is waiting on. */
    primary?: boolean
}

/**
 * Detail-pane actions as data: Resolve, Dismiss/Restore, and Refund. Create PR and Discuss are each
 * rendered separately as a standalone dropdown button (`CreatePrButton`, `DiscussReportButton`)
 * since they open a note popover rather than firing on click; rating a report lives at the end of
 * the body (`ReportFeedbackFooter`). Dismissing and resolving reuse the shared `useReportDismiss` /
 * `useReportResolve` dialog flows. Callers render these inline or inside a menu.
 */
export function useReportDetailActions(report: SignalReport): ReportDetailAction[] {
    const { reportStateChanged } = useActions(inboxBulkActionsLogic)
    const { activeTab } = useValues(inboxSceneLogic)
    const { loadSelectedReport } = useActions(inboxSceneLogic)
    const [isRestoring, setIsRestoring] = useState(false)

    const isDismissed = report.status === SignalReportStatus.SUPPRESSED
    // Resolved reports are terminal – nothing to dismiss, restore, or resolve.
    const isResolved = report.status === SignalReportStatus.RESOLVED
    // Refund leaves a report in place only when a merged PR resolved it; anything else it dismisses
    // (so the open PR gets closed), which means the view has to navigate away. Mirrors the
    // `resolved_via_merged_pr` branch in the refund endpoint.
    const staysPutOnRefund = isResolved && report.implementation_pr_merged === true

    // Once a verdict persists, broadcast so every mounted list reconciles against the server (the
    // report leaves Needs decision / Review and merge and joins Resolved or Dismissed), then return to
    // the list.
    const leaveForList = (): void => {
        reportStateChanged()
        router.actions.push(urls.inbox(activeTab))
    }

    const { isDismissing, onDismissClick } = useReportDismiss({
        reportId: report.id,
        cardTitle: report.title ?? 'Untitled report',
        report,
        surface: 'detail_pane',
        onDismissed: leaveForList,
    })

    const { isResolving, onResolveClick } = useReportResolve({
        report,
        surface: 'detail_pane',
        onResolved: leaveForList,
    })

    const { canRefund, refundDisabledReason, isRefunding, onRefundClick } = useReportRefund({
        report,
        surface: 'detail_pane',
        // Refunding dismisses the report server-side, so reconcile the lists the same way and
        // return to the list — except for resolved reports, which stay where they are.
        onRefunded: () => {
            reportStateChanged()
            if (!staysPutOnRefund) {
                router.actions.push(urls.inbox(activeTab))
            } else {
                // These reports stay on this page, so refetch: the fresh copy carries `refund`,
                // which surfaces the Refunded badge and drops Refund from the actions.
                loadSelectedReport({ id: report.id })
            }
        },
    })

    const refund: ReportDetailAction = {
        key: 'refund',
        label: 'Refund',
        icon: <IconReceipt />,
        loading: isRefunding,
        tooltip: "Refund this PR. You won't pay for it and it won't count toward your included PRs.",
        disabledReason: refundDisabledReason ?? undefined,
        onClick: onRefundClick,
    }

    const onRestoreClick = async (): Promise<void> => {
        // Prefer the mounted Dismissed list logic so it optimistically drops the row and fixes its
        // count + view badge synchronously (it also fires the API call + toast). Navigate straight back.
        const dismissedList = reportListLogic.findMounted({
            sectionKey: 'dismissed',
            listParams: INBOX_REPORT_SECTION_LIST_PARAMS.dismissed,
        })
        if (dismissedList) {
            // The list logic fires the `restore` analytics; just drive navigation here.
            dismissedList.actions.restoreReport(report.id, 'detail_pane')
            router.actions.push(urls.inbox(activeTab))
            return
        }
        // Fallback for a deep-linked detail with no mounted Dismissed list (e.g. cold load), and for
        // the flag-off Archive list, which mounts under the `resolved` key and so isn't found above.
        setIsRestoring(true)
        try {
            await api.signalReports.setState(report.id, { state: 'potential' })
            captureInboxReportAction({ report, actionType: 'restore', surface: 'detail_pane' })
            lemonToast.success('Report restored to inbox')
            // Broadcast so any mounted list (including that Archive instance) reconciles against the
            // server before we navigate back; nothing else in this path repairs its stale row + count.
            reportStateChanged()
            router.actions.push(urls.inbox(activeTab))
        } catch (error: any) {
            lemonToast.error(error?.detail || error?.message || 'Failed to restore report')
        } finally {
            setIsRestoring(false)
        }
    }

    // A resolved report is terminal, so only Discuss (rendered separately) applies. Its PR can
    // still be refunded (auto-approved by design; the weekly review watches refunded-then-merged).
    if (isResolved) {
        return canRefund ? [refund] : []
    }

    // An already-dismissed report offers Restore instead of Dismiss (and no Create PR). A refunded
    // report can't be restored (its PR can never be billed again), so Restore is hidden for it; a
    // dismissed-but-still-charged report can still be refunded.
    if (isDismissed) {
        return [
            ...(canRefund ? [refund] : []),
            ...(report.refund
                ? []
                : [
                      {
                          key: 'restore',
                          label: 'Restore',
                          icon: <IconUndo />,
                          loading: isRestoring,
                          tooltip: 'Restore this report to your inbox',
                          onClick: () => void onRestoreClick(),
                      },
                  ]),
        ]
    }

    const canResolve = canResolveReport(report)

    const resolve: ReportDetailAction = {
        key: 'resolve',
        label: 'Resolve',
        icon: <IconCheckCircle />,
        loading: isResolving,
        tooltip: 'Mark this report as done',
        // The judge found the fix already in flight, so Create PR is withheld and closing the
        // report is the step it waits on.
        primary: report.already_addressed === true,
        onClick: onResolveClick,
    }

    const actions: ReportDetailAction[] = [
        ...(canResolve ? [resolve] : []),
        {
            key: 'dismiss',
            label: 'Dismiss',
            icon: <IconHide />,
            loading: isDismissing,
            tooltip: 'Dismiss this report from your inbox',
            onClick: onDismissClick,
        },
        ...(canRefund ? [refund] : []),
    ]

    return actions
}
