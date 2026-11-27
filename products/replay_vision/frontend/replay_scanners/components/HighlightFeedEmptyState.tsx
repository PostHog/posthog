import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { RECORDINGS_BLOCK_CAUSE } from '../../logics/replayRecordingsLogic'
import { HIGHLIGHT_FEED_BLOCKS, type HighlightFeedEmptyReason, isHighlightFeedBlock } from '../highlightFeedEmptyState'
import { feedWindowPhrase, longerFeedWindow, highlightFeedLogic } from '../highlightFeedLogic'
import { visionHomeLogic } from '../visionHomeLogic'
import { HighlightFeedIntro } from './HighlightFeedIntro'
import { HighlightFeedNote } from './HighlightFeedNote'

/**
 * The one screen the Highlights tab shows when it has no clips. Each reason gets the next step
 * that would actually fill the feed, so a reader is never told to wait on scanners that cannot run.
 */
export function HighlightFeedEmptyState({ reason }: { reason: HighlightFeedEmptyReason }): JSX.Element {
    const { setOnlyMyScanners, setDateFrom } = useActions(highlightFeedLogic)
    const { dateFrom } = useValues(highlightFeedLogic)
    const { openBlockView } = useActions(visionHomeLogic)

    if (reason === 'no-scanners') {
        return <HighlightFeedIntro />
    }

    // The recordings banner above the tabs carries the fix, so the note only names the cause.
    if (reason === 'replay-off' || reason === 'no-recordings') {
        return (
            <HighlightFeedNote>
                <span>No sessions to show. {RECORDINGS_BLOCK_CAUSE[reason]}.</span>
            </HighlightFeedNote>
        )
    }

    if (isHighlightFeedBlock(reason)) {
        const block = HIGHLIGHT_FEED_BLOCKS[reason]
        return (
            <HighlightFeedNote>
                <span>No sessions to show. {block.cause}</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => openBlockView(block.view)}
                    data-attr={block.dataAttr}
                >
                    {block.actionLabel}
                </LemonButton>
            </HighlightFeedNote>
        )
    }

    const inWindow = feedWindowPhrase(dateFrom)

    if (reason === 'filtered') {
        return (
            <HighlightFeedNote>
                <span>No sessions from your scanners stood out {inWindow}.</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setOnlyMyScanners(false)}
                    data-attr="vision-highlight-feed-show-all-scanners"
                >
                    Show all scanners
                </LemonButton>
            </HighlightFeedNote>
        )
    }

    const longerWindow = longerFeedWindow(dateFrom)
    return (
        <HighlightFeedNote>
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
        </HighlightFeedNote>
    )
}
