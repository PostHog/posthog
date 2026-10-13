import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { workflowsEmailSuspensionLogic } from './workflowsEmailSuspensionLogic'

export function EmailSuspensionBanner(): JSX.Element | null {
    const { emailSendingSuspended, emailSendingSuspensionReason } = useValues(workflowsEmailSuspensionLogic)

    if (!emailSendingSuspended) {
        return null
    }

    return (
        <LemonBanner type="error" data-attr="workflows-email-suspended-banner">
            Email sending is suspended for this project. Workflow and broadcast emails are not being delivered.
            {emailSendingSuspensionReason ? <> Reason: {emailSendingSuspensionReason}.</> : null} Contact support to get
            sending re-enabled.
        </LemonBanner>
    )
}
