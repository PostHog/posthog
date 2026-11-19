import { LemonBanner } from '@posthog/lemon-ui'

import type { EmailSendingPause } from './emailSending'

export interface EmailSendingPausedBannerProps {
    pause: EmailSendingPause
    subject: 'workflow' | 'broadcast'
    /** What the pause means for this subject, said right after the pause itself. */
    effect: string
    onResume: () => void
    resuming: boolean
    resumeDisabledReason?: string
}

export function EmailSendingPausedBanner({
    pause,
    subject,
    effect,
    onResume,
    resuming,
    resumeDisabledReason,
}: EmailSendingPausedBannerProps): JSX.Element | null {
    if (!pause.paused) {
        return null
    }

    if (pause.requiresSupport) {
        return (
            <LemonBanner type="error" className="shrink-0" data-attr={`${subject}-email-paused-banner`}>
                {pause.pausedByStaff
                    ? `PostHog staff paused email sending for this ${subject} to protect delivery for everyone.`
                    : `Email sending for this ${subject} was paused again soon after it was resumed.`}{' '}
                {effect} {pause.reason} Remove old or bought addresses from the audience, then contact support to get
                sending re-enabled.
            </LemonBanner>
        )
    }

    return (
        <LemonBanner
            type="error"
            className="shrink-0"
            data-attr={`${subject}-email-paused-banner`}
            action={{
                children: 'Resume sending',
                onClick: onResume,
                // LemonButton disables itself while loading, so this is also the double-submit guard.
                loading: resuming,
                disabledReason: resumeDisabledReason,
                'data-attr': `${subject}-email-paused-resume`,
            }}
        >
            {`Email sending is paused for this ${subject}.`} {effect} {pause.reason} Remove old or bought addresses from
            the audience and stop sending to people who never open anything, then resume sending.
        </LemonBanner>
    )
}
