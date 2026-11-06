import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { Skeleton } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

import { replayRecordingsLogic } from '../../logics/replayRecordingsLogic'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { visionScannersListLogic } from '../../logics/visionScannersListLogic'
import { resolveHighlightFeedEmptyReason } from '../highlightFeedEmptyState'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { HighlightPicksShadowPreview } from './HighlightPicksShadowPreview'
import { QuillHighlightPicksBlockedState } from './QuillHighlightPicksBlockedState'
import { QuillHighlightPicksNoRecordingsState } from './QuillHighlightPicksNoRecordingsState'
import { QuillHighlightPicksQuietState } from './QuillHighlightPicksQuietState'
import { QuillHighlightPicksReplayOffState } from './QuillHighlightPicksReplayOffState'
import { QuillHighlightPicksStarter } from './QuillHighlightPicksStarter'

export function QuillHighlightPicksEmptyState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { scanners, scannersLoading } = useValues(visionScannersListLogic)
    const { quota, quotaLoading } = useValues(visionQuotaLogic)
    const { recordingsBlock, hasRecentRecordingsLoading } = useValues(replayRecordingsLogic)
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { emptyStateShown } = useActions(picksLogic)
    const large = size === 'large'
    // Waits for the probe, so the empty state is not reported once as quiet and again as no recordings.
    const loading = scannersLoading || quotaLoading || hasRecentRecordingsLoading

    const reason = loading
        ? null
        : resolveHighlightFeedEmptyReason({
              scanners,
              quota,
              recordingsBlock,
              hasFeedFilters: false,
          })

    useEffect(() => {
        if (reason) {
            emptyStateShown(reason)
        }
    }, [reason, emptyStateShown])

    if (!reason) {
        return <Skeleton className={cn('w-full rounded', large ? 'h-64' : 'h-40')} />
    }
    if (reason === 'replay-off') {
        return <QuillHighlightPicksReplayOffState size={size} />
    }
    if (reason === 'no-recordings') {
        return (
            <>
                <QuillHighlightPicksNoRecordingsState size={size} />
                <HighlightPicksShadowPreview />
            </>
        )
    }
    if (reason === 'no-scanners') {
        return (
            <>
                <QuillHighlightPicksStarter size={size} />
                <HighlightPicksShadowPreview />
            </>
        )
    }
    if (reason === 'all-disabled' || reason === 'all-capped' || reason === 'quota-exhausted') {
        return <QuillHighlightPicksBlockedState reason={reason} size={size} />
    }

    return (
        <>
            <QuillHighlightPicksQuietState size={size} />
            <HighlightPicksShadowPreview />
        </>
    )
}
