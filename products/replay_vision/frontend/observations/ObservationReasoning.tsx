import { useState } from 'react'

import { CitedMarkdown } from '../components/CitedMarkdown'
import { ClippedPreview } from '../replay_scanners/components/ClippedPreview'

/** The model's reasoning in full, clipped only when it runs past about 20 lines, which few scans do. */
export function ObservationReasoning({
    reasoning,
    segments,
    onSeek,
}: {
    reasoning: string
    segments: unknown
    onSeek: (timestampMs: number) => void
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const markdown = <CitedMarkdown text={reasoning} segments={segments} onSeek={onSeek} />
    if (expanded) {
        return markdown
    }
    return (
        <ClippedPreview
            clip="long"
            buttonLabel="Show full reasoning"
            dataAttr="vision-observation-show-reasoning"
            onOpenFull={() => setExpanded(true)}
        >
            {markdown}
        </ClippedPreview>
    )
}
