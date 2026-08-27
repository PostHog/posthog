import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { workflowLogic } from './workflowLogic'

export function WorkflowEmailPauseBanner(): JSX.Element | null {
    const { emailSendingPaused, emailSendingPausedReason, resumeEmailSendingPending } = useValues(workflowLogic)
    const { resumeEmailSending } = useActions(workflowLogic)

    if (!emailSendingPaused) {
        return null
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
