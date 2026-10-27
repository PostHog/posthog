import { useActions } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { WATCH_FEED_BLOCKS, type WatchFeedBlockReason } from '../watchFeedEmptyState'

/** Sits above cards that are still in the window, to say the feed will not get new ones and why. */
export function WatchFeedBlockedBanner({ reason }: { reason: WatchFeedBlockReason }): JSX.Element {
    const { push } = useActions(router)
    const block = WATCH_FEED_BLOCKS[reason]
    return (
        <LemonBanner
            type="warning"
            action={{
                children: block.actionLabel,
                onClick: () => push(urls.replayVision(), { tab: block.tab }),
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
