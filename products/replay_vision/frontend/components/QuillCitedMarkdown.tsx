import { useMemo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { citedMarkdown } from '../utils/citations'
import { QuillTimestampCitation } from './QuillTimestampCitation'

/** Cited scanner output as markdown. The text is hostile, so it renders no request, link or mention. */
export function QuillCitedMarkdown({
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
            lowKeyHeadings
            disableImages="all"
            disableLinks
            disableMentions
            renderTimestampRef={(timestampMs) => <QuillTimestampCitation timestampMs={timestampMs} onSeek={onSeek} />}
        >
            {markdown}
        </LemonMarkdown>
    )
}
