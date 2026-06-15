import { LemonBanner } from '@posthog/lemon-ui'

import { EndpointVersionType } from '~/types'

interface VersionBannerProps {
    version: EndpointVersionType
    currentVersion: number
    onGoToLatest: () => void
}

export function VersionBanner({ version, currentVersion, onGoToLatest }: VersionBannerProps): JSX.Element | null {
    if (version.version === currentVersion) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            action={{
                children: 'Return to latest',
                onClick: onGoToLatest,
            }}
        >
            You are viewing version v{version.version}. You can still configure an old version, but to change the
            underlying query you will need to return to the latest version.
        </LemonBanner>
    )
}
