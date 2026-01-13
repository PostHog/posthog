import { LemonBanner } from '@posthog/lemon-ui'

import { ErrorEventType } from 'lib/components/Errors/types'

interface PostHogSDKIssueBannerProps {
    event?: ErrorEventType | null
}

export function PostHogSDKIssueBanner({ event }: PostHogSDKIssueBannerProps): JSX.Element | null {
    if (!event) {
        return null
    }

    const isPostHogSDKIssue = event.properties.$exception_values?.some((v: string) =>
        v.includes('persistence.isDisabled is not a function')
    )

    if (!isPostHogSDKIssue) {
        return null
    }

    return (
        <LemonBanner
            type="error"
            action={{ to: 'https://status.posthog.com/incidents/l70cgmt7475m', children: 'Read more' }}
            className="mb-4"
        >
            This issue was captured because of a bug in the PostHog SDK. We've fixed the issue, and you won't be charged
            for any of these exception events. We recommend setting this issue's status to "Suppressed".
        </LemonBanner>
    )
}
