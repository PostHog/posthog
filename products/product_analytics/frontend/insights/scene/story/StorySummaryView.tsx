import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button, Skeleton, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'
import type { StoryChapter } from './insightStoryLogic'
import { StoryEvidenceList } from './StoryEvidenceList'
import { StoryMarkedText } from './StoryMarkedText'

export interface StorySummaryViewProps {
    insightProps: InsightLogicProps
    chapter: StoryChapter
}

export function StorySummaryView({ insightProps, chapter }: StorySummaryViewProps): JSX.Element {
    const { chapters, headline, readingStatus, storySeries } = useValues(insightStoryLogic(insightProps))
    const { loadStoryReadingRun, setActiveMoment, setPreviewMoment } = useActions(insightStoryLogic(insightProps))
    const following = chapters.slice(1)

    return (
        <div
            className="flex flex-col gap-5 starting:opacity-0 transition-opacity duration-300"
            data-attr="quill-insight-story-chapter"
        >
            <div className="flex flex-col gap-2">
                {readingStatus === 'loading' ? (
                    <div className="flex flex-col gap-2" role="status" aria-label="PostHog AI is reading the chart">
                        <Skeleton className="h-3 w-32" />
                        <Skeleton className="h-5 w-full" />
                        <Skeleton className="h-5 w-3/4" />
                    </div>
                ) : headline ? (
                    <div
                        className="flex flex-col gap-2 starting:opacity-0 transition-opacity duration-500"
                        data-attr="quill-insight-story-headline"
                    >
                        <div className="flex items-center gap-1 text-(--muted-foreground)">
                            <IconSparkles className="size-3.5 shrink-0" />
                            <Text size="xs" variant="muted">
                                PostHog AI's summary
                            </Text>
                        </div>
                        <Text size="base" weight="medium">
                            <StoryMarkedText text={headline} />
                        </Text>
                    </div>
                ) : (
                    <Text size="base" weight="medium">
                        {chapter.moment.title}
                    </Text>
                )}
                <Text size="sm">
                    <StoryMarkedText text={chapter.moment.summary} />
                </Text>
                {storySeries && storySeries.shownCount > 1 && (
                    <Text size="xs" variant="muted">
                        This follows {storySeries.label}, the biggest of the {storySeries.shownCount} series.
                    </Text>
                )}
                {readingStatus === 'failed' && (
                    <div className="flex flex-wrap items-center gap-2">
                        <Text size="xs" variant="muted">
                            PostHog AI could not read this chart. The facts do not depend on it.
                        </Text>
                        <Button
                            variant="outline"
                            size="xs"
                            onClick={() => loadStoryReadingRun()}
                            data-attr="quill-insight-story-reading-retry"
                        >
                            Try again
                        </Button>
                    </div>
                )}
            </div>
            <StoryEvidenceList insightProps={insightProps} chapter={chapter} heading="Data checks" />
            {following.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <Text size="xs" weight="medium" variant="muted">
                        What stands out
                    </Text>
                    <ol className="-mx-2 my-0 flex list-none flex-col p-0">
                        {following.map((item, index) => (
                            <li key={item.moment.id}>
                                <button
                                    type="button"
                                    data-quill
                                    className="flex w-full cursor-pointer items-center gap-2.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-start hover:bg-(--fill-hover) focus-visible:outline-2 focus-visible:outline-(--ring)"
                                    onClick={() => setActiveMoment(item.moment.id)}
                                    onMouseEnter={() => setPreviewMoment(item.moment.id)}
                                    onMouseLeave={() => setPreviewMoment(null)}
                                    onFocus={() => setPreviewMoment(item.moment.id)}
                                    onBlur={() => setPreviewMoment(null)}
                                    data-attr="quill-insight-story-contents-item"
                                >
                                    <span className="flex size-5 shrink-0 items-center justify-center rounded-full border border-(--border) text-xs font-medium text-(--muted-foreground) tabular-nums">
                                        {index + 2}
                                    </span>
                                    <Text size="sm" render={<span />}>
                                        {item.moment.title}
                                    </Text>
                                </button>
                            </li>
                        ))}
                    </ol>
                </div>
            )}
        </div>
    )
}
