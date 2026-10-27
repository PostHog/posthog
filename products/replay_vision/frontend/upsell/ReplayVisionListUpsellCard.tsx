import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

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
            <div
                className="relative flex flex-col gap-1 border-b bg-bg-light py-2 pr-8 pl-3 text-xs"
                data-attr="replay-vision-upsell-list-card"
            >
                <LemonButton
                    className="absolute top-1 right-1"
                    size="xsmall"
                    icon={<IconX />}
                    onClick={() => dismiss('list')}
                    tooltip="Hide this suggestion"
                    aria-label="Dismiss"
                    data-attr="replay-vision-upsell-list-card-dismiss"
                />
                <span className="flex items-start gap-1 font-semibold">
                    <IconSparkles className="mt-0.5 shrink-0 text-ai" />
                    <span>Save time: Replay vision can watch these for you</span>
                </span>
                <span className="text-secondary">
                    A scanner can watch every recording with these filters and answer whatever question you give it.
                </span>
                <div className="flex pt-1">
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        to={target.url}
                        onClick={() => reportClicked('list', target.cta)}
                        data-attr={`replay-vision-upsell-list-card-${target.cta}`}
                    >
                        {target.cta === 'scan_filters' ? 'Scan this filter' : 'Set up a scanner'}
                    </LemonButton>
                </div>
            </div>
        </PostHogCaptureOnViewed>
    )
}
