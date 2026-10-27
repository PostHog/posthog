import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { PostHogCaptureOnViewed } from '@posthog/react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { replayVisionUpsellLogic, upsellTargetForFilters } from './replayVisionUpsellLogic'

/** The list-card variant of the Replay vision experiment. Render it inside a bound recordings playlist. */
export function ReplayVisionListUpsellCard(): JSX.Element | null {
    const { showListCard } = useValues(replayVisionUpsellLogic)
    const { dismiss, reportClicked } = useActions(replayVisionUpsellLogic)
    const { filters } = useValues(sessionRecordingsPlaylistLogic)
    const target = useMemo(() => upsellTargetForFilters(filters), [filters])

    if (!showListCard) {
        return null
    }

    return (
        <PostHogCaptureOnViewed name="replay_vision_upsell_shown" properties={{ placement: 'list', card: 'list' }}>
            <LemonBanner
                type="ai"
                className="m-2"
                onClose={() => dismiss('list')}
                action={{
                    children: target.cta === 'scan_filters' ? 'Scan this filter' : 'Set up a scanner',
                    to: target.url,
                    onClick: () => reportClicked('list', target.cta),
                    'data-attr': `replay-vision-upsell-list-card-${target.cta}`,
                }}
            >
                <p className="m-0 font-semibold">Replay vision can watch these for you</p>
                <p className="m-0">It scans every recording in this filter and shows the ones that matter.</p>
            </LemonBanner>
        </PostHogCaptureOnViewed>
    )
}
