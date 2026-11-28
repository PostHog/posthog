import { useActions } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { HIGHLIGHT_FEED_BLOCKS, type HighlightFeedBlockReason } from '../highlightFeedEmptyState'
import { visionHomeLogic } from '../visionHomeLogic'

/** Sits above cards that are still in the window, to say the feed will not get new ones and why. */
export function HighlightFeedBlockedBanner({ reason }: { reason: HighlightFeedBlockReason }): JSX.Element {
    const { openBlockView } = useActions(visionHomeLogic)
    const block = HIGHLIGHT_FEED_BLOCKS[reason]
    return (
        <LemonBanner
            type="warning"
            action={{
                children: block.actionLabel,
                onClick: () => openBlockView(block.view),
                'data-attr': block.bannerDataAttr,
            }}
        >
            <p className="font-semibold m-0">New sessions aren't being scanned</p>
            <p className="m-0">
                {block.cause} {block.fix}
            </p>
        </LemonBanner>
    )
}
