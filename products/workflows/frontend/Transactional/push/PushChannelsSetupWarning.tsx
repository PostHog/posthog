import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { pushChannelsSetupLogic } from './pushChannelsSetupLogic'

const PUSH_SETUP_DOCS_URL = 'https://posthog.com/docs/workflows/push-notifications'

export function PushChannelsSetupWarning({ channels }: { channels: number[] }): JSX.Element | null {
    const { warning, deviceCountsLoading } = useValues(pushChannelsSetupLogic)
    const { setChannels, recheckDevices } = useActions(pushChannelsSetupLogic)

    useEffect(() => {
        setChannels(channels)
    }, [channels, setChannels])

    if (!warning) {
        return null
    }
    if (warning.kind === 'app_disconnected') {
        return (
            <div data-attr="transactional-push-app-disconnected-warning">
                <LemonBanner type="warning">
                    The selected app is no longer connected, so this notification won't reach anyone. Pick another app
                    to send it through.
                </LemonBanner>
            </div>
        )
    }
    return (
        <div data-attr="transactional-push-no-devices-warning">
            <LemonBanner
                type="warning"
                action={{
                    children: 'Check again',
                    onClick: recheckDevices,
                    loading: deviceCountsLoading,
                    'data-attr': 'transactional-push-recheck-devices',
                }}
            >
                No device has registered with {warning.appNames.join(' or ')} yet, so this notification won't reach
                anyone.{' '}
                <Link to={PUSH_SETUP_DOCS_URL} target="_blank">
                    Set up push notifications in your app
                </Link>
                , then check again.
            </LemonBanner>
        </div>
    )
}
