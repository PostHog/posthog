import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { workflowLogic } from './workflowLogic'

export function WorkflowEmailPauseBanner(): JSX.Element | null {
    const { emailSendingPaused, emailSendingPausedReason, emailSendingPausedByStaff, resumeEmailSendingPending } =
        useValues(workflowLogic)
    const { resumeEmailSending } = useActions(workflowLogic)

    if (!emailSendingPaused) {
        return null
    }

    if (emailSendingPausedByStaff) {
        return (
            <LemonBanner type="error" data-attr="workflow-email-paused-banner">
                PostHog staff paused email sending for this workflow to protect delivery for everyone. Its other steps
                still run. {emailSendingPausedReason} Remove old or bought addresses from the audience, then contact
                support to get sending re-enabled.
            </LemonBanner>
        )
    }

    return (
        <LemonBanner
            type="error"
            data-attr="workflow-email-paused-banner"
            action={{
                children: 'Resume sending',
                onClick: resumeEmailSending,
                // LemonButton disables itself while loading, so this is also the double-submit guard.
                loading: resumeEmailSendingPending,
                'data-attr': 'workflow-email-paused-resume',
            }}
        >
            Email sending is paused for this workflow. Its other steps still run, and the rest of your workflows keep
            sending. {emailSendingPausedReason} Remove old or bought addresses from the audience and stop sending to
            people who never open anything, then resume sending.
        </LemonBanner>
    )
}
