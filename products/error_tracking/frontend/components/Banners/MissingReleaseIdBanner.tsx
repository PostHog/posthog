import { useActions } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { ErrorTrackingRuntime } from 'lib/components/Errors/types'

import { MissingReleaseIdModal } from './MissingReleaseIdModal'
import { missingReleaseIdModalLogic } from './missingReleaseIdModalLogic'

export interface MissingReleaseIdBannerProps {
    eventId: string
    runtime?: ErrorTrackingRuntime
}

export function MissingReleaseIdBanner({ eventId, runtime }: MissingReleaseIdBannerProps): JSX.Element {
    const { openModal } = useActions(missingReleaseIdModalLogic({ eventId }))

    return (
        <>
            <LemonBanner
                type="warning"
                action={{
                    onClick: openModal,
                    children: 'Read more',
                    'data-attr': 'error-tracking-missing-release-id-read-more',
                }}
                className="m-2"
            >
                This exception has no release attached. Please update your PostHog SDK to the latest version.
            </LemonBanner>
            <MissingReleaseIdModal eventId={eventId} runtime={runtime} />
        </>
    )
}
