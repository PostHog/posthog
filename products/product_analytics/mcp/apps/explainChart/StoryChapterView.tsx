import { type ReactElement } from 'react'

import { Text } from '@posthog/quill'

import type { StoryChapter, StoryEvidence } from './explainChartTypes'
import { StoryEvidenceList } from './StoryEvidenceList'
import { StoryLikelyCause } from './StoryLikelyCause'
import { StoryMarkedText } from './StoryMarkedText'
import type { StoryPage } from './storyPages'

export interface StoryChapterViewProps {
    page: StoryPage & { chapter: StoryChapter }
    openLink: (url: string) => void
    canShowChart: (item: StoryEvidence) => boolean
    shownEvidenceIndex: number | null
    onToggleChart: (index: number) => void
}

export function StoryChapterView({
    page,
    openLink,
    canShowChart,
    shownEvidenceIndex,
    onToggleChart,
}: StoryChapterViewProps): ReactElement {
    const { chapter } = page
    return (
        <div
            className="grid gap-4 transition-opacity duration-300 motion-reduce:transition-none starting:opacity-0 @xl/story:grid-cols-2 @3xl/story:grid-cols-1"
            data-attr="explain-chart-chapter"
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                    <Text size="base" weight="medium" className="min-w-0 [overflow-wrap:anywhere]">
                        {page.title}
                    </Text>
                    {page.facts && (
                        <Text size="sm">
                            <StoryMarkedText text={page.facts} />
                        </Text>
                    )}
                    {!page.range && (
                        <Text size="xs" variant="muted">
                            The chart has no point for this chapter's dates, so nothing is highlighted.
                        </Text>
                    )}
                    {chapter.summary && (
                        <Text size="sm">
                            <StoryMarkedText text={chapter.summary} />
                        </Text>
                    )}
                </div>
                {chapter.cause && (
                    <StoryLikelyCause
                        cause={chapter.cause}
                        confidence={chapter.confidence}
                        confidenceReason={chapter.confidenceReason}
                    />
                )}
            </div>
            <StoryEvidenceList
                evidence={chapter.evidence}
                openLink={openLink}
                canShowChart={canShowChart}
                shownIndex={shownEvidenceIndex}
                onToggleChart={onToggleChart}
            />
        </div>
    )
}
