import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { manageDisabledReason } from './broadcastLifecycle'
import { broadcastSendingLogic } from './broadcastSendingLogic'
import { broadcastWizardLogic } from './broadcastWizardLogic'

export function BroadcastEmailPausedBanner(): JSX.Element | null {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const logic = broadcastSendingLogic(props)
    const {
        broadcast,
        emailSendingPaused,
        emailSendingPausedReason,
        emailSendingPausedByStaff,
        emailSendingPauseRequiresSupport,
        resumingEmailSending,
    } = useValues(logic)
    const { resumeEmailSending } = useActions(logic)

    if (!emailSendingPaused) {
        return null
    }

    if (emailSendingPauseRequiresSupport) {
        return (
            <LemonBanner type="error" data-attr="broadcast-email-paused-banner">
                {emailSendingPausedByStaff
                    ? 'PostHog staff paused email sending for this broadcast to protect delivery for everyone.'
                    : 'Email sending for this broadcast was paused again soon after it was resumed.'}{' '}
                {emailSendingPausedReason} Remove old or bought addresses from the audience, then contact support to get
                sending turned back on.
            </LemonBanner>
        )
    }

    return (
        <LemonBanner
            type="error"
            data-attr="broadcast-email-paused-banner"
            action={{
                children: 'Resume sending',
                onClick: resumeEmailSending,
                loading: resumingEmailSending,
                disabledReason: manageDisabledReason(broadcast?.user_access_level),
                'data-attr': 'broadcast-email-paused-resume',
            }}
        >
            Email sending is paused for this broadcast, so emails that haven't gone out yet are skipped.{' '}
            {emailSendingPausedReason} Remove old or bought addresses from the audience and stop sending to people who
            never open anything, then resume sending.
        </LemonBanner>
    )
}
