import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { urls } from 'scenes/urls'

import { replayVisionUpsellLogic } from './replayVisionUpsellLogic'

/** The list-card variant of the Replay vision experiment. */
export function ReplayVisionListUpsellCard(): JSX.Element | null {
    const { showListCard } = useValues(replayVisionUpsellLogic)
    const { dismiss, reportClicked } = useActions(replayVisionUpsellLogic)

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
                    A scanner can watch every recording and answer whatever question you give it.
                </span>
                <div className="flex pt-1">
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        to={urls.replayVisionNewScanner()}
                        onClick={() => reportClicked('list', 'set_up_scanner')}
                        data-attr="replay-vision-upsell-list-card-set-up-scanner"
                    >
                        Set up a scanner
                    </LemonButton>
                </div>
            </div>
        </PostHogCaptureOnViewed>
    )
}
