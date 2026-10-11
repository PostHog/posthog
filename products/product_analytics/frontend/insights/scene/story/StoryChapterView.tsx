import { Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import type { StoryChapter } from './insightStoryLogic'
import { StoryDigDeeper } from './StoryDigDeeper'
import { StoryEvidenceList } from './StoryEvidenceList'
import { StoryLikelyCause } from './StoryLikelyCause'
import { StoryMarkedText } from './StoryMarkedText'

export interface StoryChapterViewProps {
    insightProps: InsightLogicProps
    chapter: StoryChapter
}

export function StoryChapterView({ insightProps, chapter }: StoryChapterViewProps): JSX.Element {
    return (
        <div
            className="flex flex-col gap-5 starting:opacity-0 transition-opacity duration-300"
            data-attr="quill-insight-story-chapter"
        >
            <div className="flex flex-col gap-2">
                <Text size="base" weight="medium">
                    {chapter.moment.title}
                </Text>
                <Text size="sm">
                    <StoryMarkedText text={chapter.moment.summary} />
                </Text>
            </div>
            <StoryLikelyCause insightProps={insightProps} chapter={chapter} />
            <StoryEvidenceList insightProps={insightProps} chapter={chapter} heading="Evidence" />
            <StoryDigDeeper insightProps={insightProps} chapter={chapter} />
        </div>
    )
}
