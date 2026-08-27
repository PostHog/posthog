import { useMemo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { citedMarkdown } from '../utils/citations'
import { TimestampCitation } from './TimestampCitation'

/**
 * A scanner's cited free-text output, rendered as markdown with its citations as seek controls.
 *
 * Scanners write reasoning that carries structure — a lead-in naming what they found, then the evidence —
 * and that structure only reads as structure once it is rendered. Images are treated as untrusted: the
 * text is model output derived from a customer recording, so a page that talked the model into writing an
 * image tag must not get to fire a request from the reader's browser.
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
            renderTimestampRef={(timestampMs) => <TimestampCitation timestampMs={timestampMs} onSeek={onSeek} />}
        >
            {markdown}
        </LemonMarkdown>
    )
}
