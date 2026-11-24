import { LemonBanner } from '@posthog/lemon-ui'
import { Button, Item, ItemActions, ItemContent, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EndpointVersionType } from '~/types'

interface VersionBannerProps {
    version: EndpointVersionType
    currentVersion: number
    onGoToLatest: () => void
}

export function VersionBanner({ version, currentVersion, onGoToLatest }: VersionBannerProps): JSX.Element | null {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (version.version === currentVersion) {
        return null
    }

    const message = `You are viewing version v${version.version}. You can still configure an old version, but to change the underlying query you will need to return to the latest version.`

    if (todayRailNav) {
        return (
            <Item variant="outline" size="sm" tone="warning" className="flex-wrap" data-quill>
                <ItemContent className="min-w-0">
                    <Text size="xs" render={<div />} className="m-0">
                        {message}
                    </Text>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={onGoToLatest} data-attr="endpoint-version-return-to-latest">
                        Return to latest
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    return (
        <LemonBanner
            type="warning"
            action={{
                children: 'Return to latest',
                onClick: onGoToLatest,
            }}
        >
            {message}
        </LemonBanner>
    )
}
