import { useMemo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { citedMarkdown } from '../utils/citations'
import { TimestampCitation } from './TimestampCitation'

/** Cited scanner output as markdown. The text is hostile, so it renders no request, link or mention. */
export function CitedMarkdown({
    text,
    segments,
    onSeek,
}: {
    text: string
    segments: unknown
    onSeek?: (timestampMs: number) => void
}): JSX.Element {
    const markdown = useMemo(() => citedMarkdown(text, segments), [text, segments])
    return (
        <LemonMarkdown
            className="text-sm"
            // A heading inside one card's body is a lead-in, not a section of the page.
            lowKeyHeadings
            disableImages="all"
            disableLinks
            disableMentions
            renderTimestampRef={(timestampMs) => <TimestampCitation timestampMs={timestampMs} onSeek={onSeek} />}
        >
            {markdown}
        </LemonMarkdown>
    )
}
