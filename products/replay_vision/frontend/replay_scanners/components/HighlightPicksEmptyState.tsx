import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import { resolveHighlightFeedEmptyReason } from '../highlightFeedEmptyState'
import { HighlightPicksBlockedState } from './HighlightPicksBlockedState'
import { HighlightPicksQuietState } from './HighlightPicksQuietState'
import { HighlightPicksReplayOffState } from './HighlightPicksReplayOffState'
import { HighlightPicksStarter } from './HighlightPicksStarter'

export function HighlightPicksEmptyState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { scanners, scannersLoading } = useValues(visionScannersListLogic)
    const { quota, quotaLoading } = useValues(visionQuotaLogic)
    const { currentTeam } = useValues(teamLogic)
    const large = size === 'large'

    if (scannersLoading || quotaLoading) {
        return <LemonSkeleton className={cn('w-full rounded', large ? 'h-64' : 'h-40')} />
    }

    const reason = resolveHighlightFeedEmptyReason({
        scanners,
        quota,
        sessionRecordingOptIn: currentTeam?.session_recording_opt_in ?? null,
        hasFeedFilters: false,
    })
    if (reason === 'replay-off') {
        return <HighlightPicksReplayOffState size={size} />
    }
    if (reason === 'no-scanners') {
        return <HighlightPicksStarter size={size} />
    }
    if (reason === 'all-disabled' || reason === 'all-capped' || reason === 'quota-exhausted') {
        return <HighlightPicksBlockedState reason={reason} size={size} />
    }

    return <HighlightPicksQuietState size={size} />
}
