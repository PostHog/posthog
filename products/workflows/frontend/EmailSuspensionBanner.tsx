import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { EMAIL_SENDING_SUSPENDED_MESSAGE } from './Channels/emailSendingMessages'
import { workflowsEmailSuspensionLogic } from './workflowsEmailSuspensionLogic'

export function EmailSuspensionBanner(): JSX.Element | null {
    const { emailSendingSuspended, emailSendingSuspensionReason } = useValues(workflowsEmailSuspensionLogic)

    if (!emailSendingSuspended) {
        return null
    }

    return (
        <LemonBanner type="error" data-attr="workflows-email-suspended-banner">
            {EMAIL_SENDING_SUSPENDED_MESSAGE}
            {emailSendingSuspensionReason ? <> Reason: {emailSendingSuspensionReason}.</> : null} Contact support to get
            sending re-enabled.
        </LemonBanner>
    )
}
