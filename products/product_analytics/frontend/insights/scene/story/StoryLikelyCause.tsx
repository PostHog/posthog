import { useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Badge, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'
import type { StoryChapter, StoryConfidence } from './insightStoryLogic'
import { StoryMarkedText } from './StoryMarkedText'

const CONFIDENCE: Record<StoryConfidence, { label: string; variant: 'success' | 'info' | 'default'; why: string }> = {
    high: {
        label: 'High confidence',
        variant: 'success',
        why: 'One finding in the evidence accounts for most of this change.',
    },
    medium: {
        label: 'Medium confidence',
        variant: 'info',
        why: 'The evidence points at a cause, but that cause does not account for most of the change.',
    },
    guess: {
        label: 'A guess',
        variant: 'default',
        why: "Nothing in the evidence names a cause. This is PostHog AI's best guess.",
    },
}

export function StoryLikelyCause({
    insightProps,
    chapter,
}: {
    insightProps: InsightLogicProps
    chapter: StoryChapter
}): JSX.Element | null {
    const { readingStatus } = useValues(insightStoryLogic(insightProps))
    const isLoading = readingStatus === 'loading' && chapter.hasCause

    if (!isLoading && !chapter.reading) {
        return null
    }
    const confidence = chapter.reading ? CONFIDENCE[chapter.reading.confidence] : null

    return (
        <div className="flex flex-col gap-1.5" data-attr="quill-insight-story-reading">
            <div className="flex items-center justify-between gap-2">
                <Text size="xs" weight="medium" variant="muted">
                    Likely cause
                </Text>
                {!isLoading && confidence && (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <button
                                    type="button"
                                    data-quill
                                    className="cursor-default rounded-md border-0 bg-transparent p-0 focus-visible:outline-2 focus-visible:outline-(--ring)"
                                    data-attr="quill-insight-story-confidence"
                                />
                            }
                        >
                            <Badge variant={confidence.variant}>{confidence.label}</Badge>
                        </TooltipTrigger>
                        <TooltipContent side="left">{confidence.why}</TooltipContent>
                    </Tooltip>
                )}
            </div>
            {isLoading || !chapter.reading ? (
                <Skeleton className="h-16 w-full" />
            ) : (
                <div className="flex flex-col gap-2 rounded-md bg-(--muted) p-3 starting:opacity-0 transition-opacity duration-500">
                    <Text size="sm">
                        <StoryMarkedText text={chapter.reading.text} />
                    </Text>
                    <div className="flex items-center gap-1 text-(--muted-foreground)">
                        <IconSparkles className="size-3.5 shrink-0" />
                        <Text size="xs" variant="muted">
                            PostHog AI
                        </Text>
                    </div>
                </div>
            )}
        </div>
    )
}
