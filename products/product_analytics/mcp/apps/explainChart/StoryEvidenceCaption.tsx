import type { ReactElement } from 'react'

import { Text } from '@posthog/quill'

import { storyTextParts } from './storyMarks'

export function StoryEvidenceCaption({ text }: { text: string }): ReactElement {
    return (
        <Text
            size="sm"
            className="min-w-0 truncate"
            title={text.replaceAll('**', '')}
            data-attr="explain-chart-evidence-caption"
        >
            {storyTextParts(text).map((part, index) => (
                <span key={index} className={part.kind ? 'font-medium' : 'text-secondary'}>
                    {part.text}
                </span>
            ))}
        </Text>
    )
}
