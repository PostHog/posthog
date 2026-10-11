import { Highlight } from '@posthog/quill'
import type { HighlightColor } from '@posthog/quill'

import { storyTextParts } from './storyMarks'
import type { StoryMarkKind } from './storyMarks'

// The same colors as the words of the question above the chart: its dates, its measure, and what it is split by.
const COLORS: Record<StoryMarkKind, HighlightColor> = {
    date: 'orange',
    value: 'purple',
    name: 'green',
}

const STROKE_GAP_MS = 180

export function StoryMarkedText({ text }: { text: string }): JSX.Element {
    let marked = 0
    return (
        <>
            {storyTextParts(text).map((part, index) =>
                part.kind ? (
                    <Highlight
                        key={index}
                        color={COLORS[part.kind]}
                        animate
                        delay={marked++ * STROKE_GAP_MS}
                        className="font-medium [--mark:transparent]"
                    >
                        {part.text}
                    </Highlight>
                ) : (
                    <span key={index}>{part.text}</span>
                )
            )}
        </>
    )
}
