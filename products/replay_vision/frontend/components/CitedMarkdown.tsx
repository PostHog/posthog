import { useMemo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { citedMarkdown } from '../utils/citations'
import { TimestampCitation } from './TimestampCitation'

/**
 * A scanner's cited free-text output, rendered as markdown with its citations as seek controls.
 *
 * Scanners write reasoning that carries structure — a lead-in naming what they found, then the evidence —
 * and that structure only reads as structure once it is rendered.
 *
 * The text is model output derived from a customer recording, so it is treated as hostile: an image must
 * not get to fire a request from the reader's browser, and no link may be clickable. A citation is the
 * one interactive thing here, and it seeks a player rather than navigating anywhere.
 */
export function CitedMarkdown({
    text,
    segments,
    onSeek,
}: {
    text: string
    segments: unknown
    /** Called with timestamp_ms when a citation is clicked. If omitted, citations render as plain timestamps. */
    onSeek?: (timestampMs: number) => void
}): JSX.Element {
    const markdown = useMemo(() => citedMarkdown(text, segments), [text, segments])
    return (
        <LemonMarkdown
            className="text-sm"
            // A heading inside one card's body is a lead-in, not a section of the page.
            lowKeyHeadings
            disableImages
            disableLinks
            renderTimestampRef={(timestampMs) => <TimestampCitation timestampMs={timestampMs} onSeek={onSeek} />}
        >
            {markdown}
        </LemonMarkdown>
    )
}
