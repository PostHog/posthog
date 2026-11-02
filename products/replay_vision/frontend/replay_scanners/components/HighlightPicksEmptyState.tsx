import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import { resolveHighlightFeedEmptyReason } from '../highlightFeedEmptyState'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { HighlightPicksBlockedState } from './HighlightPicksBlockedState'
import { HighlightPicksNoRecordingsState } from './HighlightPicksNoRecordingsState'
import { HighlightPicksQuietState } from './HighlightPicksQuietState'
import { HighlightPicksReplayOffState } from './HighlightPicksReplayOffState'
import { HighlightPicksShadowPreview } from './HighlightPicksShadowPreview'
import { HighlightPicksStarter } from './HighlightPicksStarter'

export function HighlightPicksEmptyState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { scanners, scannersLoading } = useValues(visionScannersListLogic)
    const { quota, quotaLoading } = useValues(visionQuotaLogic)
    const { currentTeam } = useValues(teamLogic)
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { emptyStateShown } = useActions(picksLogic)
    const { status: replayStatus } = useValues(productSetupStatusLogic({ productKey: ProductKey.SESSION_REPLAY }))
    const large = size === 'large'
    const loading = scannersLoading || quotaLoading

    const reason = loading
        ? null
        : resolveHighlightFeedEmptyReason({
              scanners,
              quota,
              sessionRecordingOptIn: currentTeam?.session_recording_opt_in ?? null,
              hasFeedFilters: false,
              hasRecordings:
                  replayStatus === 'has-data'
                      ? true
                      : replayStatus === 'needs-setup' || replayStatus === 'waiting-for-data'
                        ? false
                        : null,
          })

    useEffect(() => {
        if (reason) {
            emptyStateShown(reason)
        }
    }, [reason, emptyStateShown])

    if (!reason) {
        return <LemonSkeleton className={cn('w-full rounded', large ? 'h-64' : 'h-40')} />
    }
    if (reason === 'replay-off') {
        return <HighlightPicksReplayOffState size={size} />
    }
    if (reason === 'no-recordings') {
        return (
            <>
                <HighlightPicksNoRecordingsState size={size} />
                <HighlightPicksShadowPreview />
            </>
        )
    }
    if (reason === 'no-scanners') {
        return (
            <>
                <HighlightPicksStarter size={size} />
                <HighlightPicksShadowPreview />
            </>
        )
    }
    if (reason === 'all-disabled' || reason === 'all-capped' || reason === 'quota-exhausted') {
        return <HighlightPicksBlockedState reason={reason} size={size} />
    }

    return (
        <>
            <HighlightPicksQuietState size={size} />
            <HighlightPicksShadowPreview />
        </>
    )
}
