import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { RATE_THRESHOLDS, formatRate } from './emailReputation'
import { workflowsReputationLogic } from './workflowsReputationLogic'

export function WorkflowsEmailSuspendedBanner(): JSX.Element | null {
    const { suspensionCause, suspensionReason, awsReputation, sendingAllowance } = useValues(workflowsReputationLogic)
    const { requestSendingReview } = useActions(workflowsReputationLogic)

    if (!suspensionCause) {
        return null
    }

    const hasFindings = (awsReputation?.findings.length ?? 0) > 0

    return (
        <LemonBanner
            type="error"
            data-attr="workflows-reputation-suspended-banner"
            action={{
                children: 'Request a review',
                onClick: requestSendingReview,
                'data-attr': 'workflows-reputation-request-review',
            }}
        >
            <p>
                {suspensionCause === 'staff'
                    ? 'PostHog suspended workflow email for this project to protect delivery for everyone.'
                    : 'Our email provider paused workflow email for this project.'}{' '}
                Your workflows still run, but every email step is skipped.
                {suspensionReason ? ` Reason: ${suspensionReason}.` : null}
            </p>
            <p className="mb-1">Before sending can resume:</p>
            <ul className="list-disc pl-4 mb-2">
                {hasFindings && <li>Fix the sending health findings listed below.</li>}
                <li>
                    Get the bounce rate under {formatRate(RATE_THRESHOLDS.bounce.elevated)} and the spam complaint rate
                    under {formatRate(RATE_THRESHOLDS.complaint.elevated)}.
                </li>
                <li>Remove old or bought addresses from your audiences, and stop new ones getting in.</li>
            </ul>
            <p className="mb-0">
                Then request a review.{' '}
                {suspensionCause === 'staff'
                    ? 'We check the current state and lift the suspension if it is safe to send again. A person reviews each request, so we cannot promise a date.'
                    : 'We check the current state and ask our email provider to re-enable sending. The provider makes the final decision, so we cannot promise a date.'}
                {sendingAllowance?.enforced
                    ? ' Once sending is back, your allowance starts at a low tier and grows again as your workflows send cleanly.'
                    : null}
            </p>
        </LemonBanner>
    )
}
