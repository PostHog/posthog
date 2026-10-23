import { type ReactElement } from 'react'

import { Highlight } from '@posthog/quill'

import { storyTextParts } from './storyMarks'

const STROKE_GAP_MS = 180

/** Names get a highlight. Dates and values are only set in a heavier weight, so a sentence stays readable. */
export function StoryMarkedText({ text }: { text: string }): ReactElement {
    let marked = 0
    return (
        <>
            {storyTextParts(text).map((part, index) =>
                part.kind === 'name' ? (
                    <Highlight
                        key={index}
                        color="green"
                        animate
                        delay={marked++ * STROKE_GAP_MS}
                        className="font-medium [--mark:transparent]"
                    >
                        {part.text}
                    </Highlight>
                ) : part.kind ? (
                    <span key={index} className="font-medium">
                        {part.text}
                    </span>
                ) : (
                    <span key={index}>{part.text}</span>
                )
            )}
        </>
    )
}
