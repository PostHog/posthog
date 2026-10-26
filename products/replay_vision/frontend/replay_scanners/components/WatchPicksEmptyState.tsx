import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import { resolveWatchFeedEmptyReason } from '../watchFeedEmptyState'
import { WatchPicksBlockedState } from './WatchPicksBlockedState'
import { WatchPicksQuietState } from './WatchPicksQuietState'
import { WatchPicksReplayOffState } from './WatchPicksReplayOffState'
import { WatchPicksStarter } from './WatchPicksStarter'

export function WatchPicksEmptyState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { scanners, scannersLoading } = useValues(visionScannersListLogic)
    const { quota, quotaLoading } = useValues(visionQuotaLogic)
    const { currentTeam } = useValues(teamLogic)
    const large = size === 'large'

    if (scannersLoading || quotaLoading) {
        return <LemonSkeleton className={cn('w-full rounded', large ? 'h-64' : 'h-40')} />
    }

    const reason = resolveWatchFeedEmptyReason({
        scanners,
        quota,
        sessionRecordingOptIn: currentTeam?.session_recording_opt_in ?? null,
        hasFeedFilters: false,
    })
    if (reason === 'replay-off') {
        return <WatchPicksReplayOffState size={size} />
    }
    if (reason === 'no-scanners') {
        return <WatchPicksStarter size={size} />
    }
    if (reason === 'all-disabled' || reason === 'all-capped' || reason === 'quota-exhausted') {
        return <WatchPicksBlockedState reason={reason} size={size} />
    }

    return <WatchPicksQuietState size={size} />
}
