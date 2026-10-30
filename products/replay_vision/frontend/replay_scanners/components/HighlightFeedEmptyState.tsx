import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { HIGHLIGHT_FEED_BLOCKS, type HighlightFeedEmptyReason, isHighlightFeedBlock } from '../highlightFeedEmptyState'
import { feedWindowPhrase, longerFeedWindow, highlightFeedLogic } from '../highlightFeedLogic'
import { HighlightFeedIntro } from './HighlightFeedIntro'

function DashedNote({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 text-sm text-secondary border border-dashed rounded p-6 text-center">
            {children}
        </div>
    )
}

/**
 * The one screen the Highlights tab shows when it has no clips. Each reason gets the next step
 * that would actually fill the feed, so a reader is never told to wait on scanners that cannot run.
 */
export function HighlightFeedEmptyState({ reason }: { reason: HighlightFeedEmptyReason }): JSX.Element {
    const { setOnlyMyScanners, setDateFrom } = useActions(highlightFeedLogic)
    const { dateFrom } = useValues(highlightFeedLogic)
    const { push } = useActions(router)

    if (reason === 'no-scanners') {
        return <HighlightFeedIntro />
    }

    if (isHighlightFeedBlock(reason)) {
        const block = HIGHLIGHT_FEED_BLOCKS[reason]
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

    const inWindow = feedWindowPhrase(dateFrom)

    if (reason === 'filtered') {
        return (
            <DashedNote>
                <span>No sessions from your scanners stood out {inWindow}.</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setOnlyMyScanners(false)}
                    data-attr="vision-highlight-feed-show-all-scanners"
                >
                    Show all scanners
                </LemonButton>
            </DashedNote>
        )
    }

    const longerWindow = longerFeedWindow(dateFrom)
    return (
        <DashedNote>
            <span>No sessions stood out {inWindow}.</span>
            {longerWindow && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setDateFrom(longerWindow.value)}
                    data-attr="vision-highlight-feed-longer-window"
                >
                    Show {longerWindow.label.toLowerCase()}
                </LemonButton>
            )}
        </DashedNote>
    )
}
