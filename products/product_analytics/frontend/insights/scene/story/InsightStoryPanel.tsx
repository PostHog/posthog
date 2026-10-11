import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'
import { StoryChapterView } from './StoryChapterView'
import { StorySteps } from './StorySteps'
import { StorySummaryView } from './StorySummaryView'
import { StoryZoomReturn } from './StoryZoomReturn'

export function InsightStoryPanel({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { chapters, activeChapter, activeIndex, insightDataLoading } = useValues(insightStoryLogic(insightProps))
    const { closeStory, stepMoment } = useActions(insightStoryLogic(insightProps))

    if (!activeChapter) {
        return null
    }
    const next = chapters[activeIndex + 1]

    return (
        <aside
            className="relative shrink-0 border-t border-(--border) @3xl/story:w-80 @3xl/story:border-t-0 @3xl/story:border-l @5xl/story:w-96"
            aria-label="The story of this chart"
            data-attr="quill-insight-story"
        >
            {/* Next to the chart, the story takes the chart's height and the chapter scrolls inside it. */}
            <div className="flex flex-col @3xl/story:absolute @3xl/story:inset-0">
                <div className="flex items-center justify-between gap-2 border-b border-(--border) py-2 ps-5 pe-3">
                    <StorySteps insightProps={insightProps} />
                    <Button
                        variant="default"
                        size="icon-sm"
                        aria-label="Close the story"
                        onClick={() => closeStory()}
                        data-attr="quill-insight-story-close"
                    >
                        <IconX />
                    </Button>
                </div>
                <StoryZoomReturn insightProps={insightProps} />
                {/* While the chart loads new data, the page on show belongs to the old data. */}
                <div
                    className={`min-h-0 flex-1 overflow-y-auto p-5 transition-opacity duration-300 ${
                        insightDataLoading ? 'pointer-events-none opacity-40' : ''
                    }`}
                    aria-busy={insightDataLoading}
                >
                    {activeChapter.moment.kind === 'overview' ? (
                        <StorySummaryView insightProps={insightProps} chapter={activeChapter} />
                    ) : (
                        <StoryChapterView
                            key={activeChapter.moment.id}
                            insightProps={insightProps}
                            chapter={activeChapter}
                        />
                    )}
                </div>
                <div className="flex items-center justify-between gap-3 border-t border-(--border) py-2 ps-5 pe-3">
                    <Text size="xs" variant="muted" className="min-w-0 truncate">
                        {next ? `Next: ${next.moment.title}` : ''}
                    </Text>
                    <div className="flex shrink-0 gap-1">
                        {activeIndex > 0 && (
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => stepMoment(-1)}
                                data-attr="quill-insight-story-back"
                            >
                                Back
                            </Button>
                        )}
                        {next ? (
                            <Button
                                variant="primary"
                                size="sm"
                                onClick={() => stepMoment(1)}
                                data-attr="quill-insight-story-next"
                            >
                                Next
                            </Button>
                        ) : (
                            <Button
                                variant="primary"
                                size="sm"
                                onClick={() => closeStory()}
                                data-attr="quill-insight-story-done"
                            >
                                Done
                            </Button>
                        )}
                    </div>
                </div>
            </div>
        </aside>
    )
}
