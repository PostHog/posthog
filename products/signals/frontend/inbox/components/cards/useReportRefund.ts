import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { signalsReportsRefundCreate } from 'products/signals/frontend/generated/api'

import {
    captureInboxReportAction,
    captureInboxReportRefundBlocked,
    InboxReportActionSurface,
} from '../../inboxAnalytics'
import { SignalReport, SignalReportStatus } from '../../types'
import { refundBlockFor } from '../../utils/refundBlock'
import { openRefundReportDialog } from '../shell/RefundReportDialog'

/**
 * Shared refund handler for the inbox cards and the detail pane, mirroring `useReportDismiss`.
 * Opens the refund dialog and posts to the refund endpoint; the backend freezes the billing path,
 * dismisses the report, and (when needed) kicks off the billing credit. Offered only when the flag
 * is on and the report has a billable PR that hasn't been refunded — the server enforces the same
 * rules, so `canRefund` is purely a display gate.
 *
 * When the backend already knows a refund would be refused, the returned label, tooltip, and click
 * describe the next step instead: support for a reason support can fix, a disabled explanation
 * otherwise.
 */
export function useReportRefund({
    report,
    surface,
    onRefunded,
}: {
    report: SignalReport
    /** Which surface the refund was triggered from, for the `refund` analytics. */
    surface?: InboxReportActionSurface
    /** Fired once the refund API call succeeds (the report is dismissed server-side by then). */
    onRefunded?: () => void
}): {
    canRefund: boolean
    refundLabel: string
    refundTooltip: string
    refundDisabledReason: string | null
    isRefunding: boolean
    onRefundClick: (event: React.MouseEvent) => void
} {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { openSupportForm } = useActions(supportLogic)
    const [isRefunding, setIsRefunding] = useState(false)

    // Exempt reports ("Free" tag) were never charged, so there is nothing to refund; a report
    // without a PR was never billed either. One refund per report, ever.
    const canRefund =
        !!featureFlags[FEATURE_FLAGS.SIGNALS_PR_REFUNDS] &&
        !!report.implementation_pr_url &&
        !report.refund &&
        !report.billing_exempt_reason

    // Backend-owned eligibility: a visible button whose POST would only ever 400.
    const blockedReason = canRefund ? (report.refund_ineligibility_reason ?? null) : null
    const block = refundBlockFor(blockedReason)
    const routesToSupport = !!block?.routesToSupport
    const actionSurface = surface ?? 'list_row'

    // A disabled control is never clicked, so the blocked state reports itself when it renders.
    // Deps are the identity of that state, so a refetch of the same report stays one event.
    useEffect(() => {
        if (blockedReason) {
            captureInboxReportRefundBlocked({
                report,
                reason: blockedReason,
                hasSupportRoute: routesToSupport,
                surface: actionSurface,
            })
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [report.id, blockedReason, routesToSupport, actionSurface])

    const onSupportClick = (event: React.MouseEvent): void => {
        event.preventDefault()
        event.stopPropagation()
        captureInboxReportAction({
            report,
            actionType: 'refund_support',
            surface: actionSurface,
            extra: { refund_ineligibility_reason: blockedReason },
        })
        openSupportForm({
            kind: 'support',
            // Billing questions are answered on every plan, so the credit request reaches us
            // regardless of whether the plan includes support.
            billing_issue: true,
            isEmailFormOpen: true,
            message: [
                "I'd like a credit for a self-driving PR that can no longer be refunded in the app.",
                '',
                `Report: ${report.title ?? report.id}`,
                `PR: ${report.implementation_pr_url ?? 'unknown'}`,
            ].join('\n'),
        })
    }

    const onRefundClick = (event: React.MouseEvent): void => {
        event.preventDefault()
        event.stopPropagation()
        openRefundReportDialog({
            reportTitle: report.title,
            // A merged PR resolved the report? The refund leaves it in Resolved instead of dismissing
            // it (the `resolved_via_merged_pr` branch in the refund endpoint), so the copy must not
            // promise a dismissal.
            staysResolved: report.status === SignalReportStatus.RESOLVED && report.implementation_pr_merged === true,
            onConfirm: async ({ reason, note }) => {
                if (isRefunding || currentTeamId == null) {
                    return
                }
                setIsRefunding(true)
                try {
                    await signalsReportsRefundCreate(String(currentTeamId), report.id, {
                        reason,
                        ...(note ? { note } : {}),
                    })
                    captureInboxReportAction({
                        report,
                        actionType: 'refund',
                        surface: actionSurface,
                        extra: { refund_reason: reason, ...(note ? { refund_note: note } : {}) },
                    })
                    lemonToast.success("PR refunded. You won't be charged for it.")
                    onRefunded?.()
                } catch (error: any) {
                    lemonToast.error(error?.detail || error?.error || error?.message || 'Failed to refund this PR')
                    throw error // keep the dialog open so the user can retry
                } finally {
                    setIsRefunding(false)
                }
            },
        })
    }

    return {
        canRefund,
        refundLabel: routesToSupport ? 'Request a credit' : 'Refund',
        refundTooltip:
            block?.copy ?? "Refund this PR. You won't pay for it and it won't count toward your included PRs.",
        refundDisabledReason: routesToSupport ? null : (block?.copy ?? null),
        isRefunding,
        onRefundClick: routesToSupport ? onSupportClick : onRefundClick,
    }
}
