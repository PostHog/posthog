import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { WATCH_FEED_BLOCKS, type WatchFeedEmptyReason, isWatchFeedBlock } from '../watchFeedEmptyState'
import { FEED_DATE_OPTIONS, feedWindowPhrase, watchFeedLogic } from '../watchFeedLogic'
import { WatchFeedIntro } from './WatchFeedIntro'

function DashedNote({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 text-sm text-secondary border border-dashed rounded p-6 text-center">
            {children}
        </div>
    )
}

/**
 * The one screen the What to watch tab shows when it has no clips. Each reason gets the next step
 * that would actually fill the feed, so a reader is never told to wait on scanners that cannot run.
 * A block gets a plain note here; the warning banner is for a feed that still has cards to show.
 */
export function WatchFeedEmptyState({ reason }: { reason: WatchFeedEmptyReason }): JSX.Element {
    const { setOnlyMyScanners, setDateFrom } = useActions(watchFeedLogic)
    const { dateFrom } = useValues(watchFeedLogic)
    const { push } = useActions(router)

    if (reason === 'no-scanners') {
        return <WatchFeedIntro />
    }

    if (isWatchFeedBlock(reason)) {
        const block = WATCH_FEED_BLOCKS[reason]
        return (
            <DashedNote>
                <span>No sessions to show. {block.cause}</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => push(urls.replayVision(), { tab: block.tab })}
                    data-attr={block.dataAttr}
                >
                    {block.actionLabel}
                </LemonButton>
            </DashedNote>
        )
    }

    const windowIndex = FEED_DATE_OPTIONS.findIndex((option) => option.value === dateFrom)
    const inWindow = feedWindowPhrase(dateFrom)
    const longerWindow = windowIndex >= 0 ? FEED_DATE_OPTIONS[windowIndex + 1] : undefined

    if (reason === 'filtered') {
        return (
            <DashedNote>
                <span>No sessions from your scanners stood out {inWindow}.</span>
                <LemonButton type="secondary" size="small" onClick={() => setOnlyMyScanners(false)}>
                    Show all scanners
                </LemonButton>
            </DashedNote>
        )
    }

    return (
        <DashedNote>
            <span>No sessions stood out {inWindow}.</span>
            {longerWindow && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setDateFrom(longerWindow.value)}
                    data-attr="vision-watch-feed-longer-window"
                >
                    Show {longerWindow.label.toLowerCase()}
                </LemonButton>
            )}
        </DashedNote>
    )
}
