import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { BillingExemptReasonEnumApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReport } from '../../types'

const EXEMPT_TOOLTIPS: Record<BillingExemptReasonEnumApi, string> = {
    [BillingExemptReasonEnumApi.PosthogHealthCheck]:
        'This report came from a PostHog health check, so creating a pull request for it is free.',
    [BillingExemptReasonEnumApi.PosthogOnboarding]:
        'This report was created during onboarding, so creating a pull request for it is free.',
    [BillingExemptReasonEnumApi.PosthogSystem]:
        'This report came from a PostHog-managed signal, so creating a pull request for it is free.',
}

const EXEMPT_TOOLTIP_DEFAULT =
    'PostHog marked this report as free, so creating a pull request for it will not be billed.'

function refundTooltip(refund: NonNullable<SignalReport['refund']>): string {
    if (refund.billing_path === 'excluded') {
        return "This PR was refunded before it was billed. You won't pay for it, and it doesn't count toward your included PRs."
    }
    if (refund.credit_amount_usd != null) {
        return `This PR was refunded. $${refund.credit_amount_usd} was credited toward your next invoice, and it doesn't count toward your included PRs.`
    }
    return "This PR was refunded. The credit is being processed, and it doesn't count toward your included PRs."
}

/**
 * Permanent billing marker for a report: "Refunded" once its PR has been refunded, or "Free" when
 * the report is system-marked never-billable (PostHog-system origin, e.g. a health-check scout
 * finding). Null for ordinary billable reports.
 */
export function SignalReportBillingBadge({ report }: { report: SignalReport }): JSX.Element | null {
    if (report.refund) {
        return (
            <Tooltip title={refundTooltip(report.refund)}>
                <LemonTag size="small" type="completion">
                    Refunded
                </LemonTag>
            </Tooltip>
        )
    }
    if (report.billing_exempt_reason) {
        const tooltip =
            EXEMPT_TOOLTIPS[report.billing_exempt_reason as BillingExemptReasonEnumApi] ?? EXEMPT_TOOLTIP_DEFAULT
        return (
            <Tooltip title={tooltip}>
                <LemonTag size="small" type="success">
                    Free
                </LemonTag>
            </Tooltip>
        )
    }
    return null
}
