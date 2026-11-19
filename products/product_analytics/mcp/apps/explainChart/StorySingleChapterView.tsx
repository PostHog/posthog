import { type ReactElement } from 'react'

import { Text } from '@posthog/quill'

import { StoryChapterView, type StoryChapterViewProps } from './StoryChapterView'
import { StoryMarkedText } from './StoryMarkedText'

export interface StorySingleChapterViewProps extends StoryChapterViewProps {
    headline: string
    /** Which series the story follows, when the chart has more than one. */
    seriesNote: string | null
    warnings?: string[]
}

export function StorySingleChapterView({
    headline,
    seriesNote,
    warnings = [],
    ...chapterProps
}: StorySingleChapterViewProps): ReactElement {
    return (
        <div className="flex flex-col gap-4" data-attr="explain-chart-single-chapter">
            <div className="flex flex-col gap-2 border-b border-border pb-4">
                <Text size="base" weight="medium">
                    <StoryMarkedText text={headline} />
                </Text>
                {seriesNote && (
                    <Text size="xs" variant="muted">
                        {seriesNote}
                    </Text>
                )}
                {warnings.map((warning, index) => (
                    <Text key={index} size="xs" variant="muted" data-attr="explain-chart-warning">
                        {warning}
                    </Text>
                ))}
            </div>
            <StoryChapterView {...chapterProps} />
        </div>
    )
}
