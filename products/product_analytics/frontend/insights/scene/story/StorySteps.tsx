import { useActions, useValues } from 'kea'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { insightStoryLogic } from './insightStoryLogic'

export function StorySteps({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { chapters, activeIndex } = useValues(insightStoryLogic(insightProps))
    const { setActiveMoment, setPreviewMoment } = useActions(insightStoryLogic(insightProps))

    return (
        <ol className="m-0 flex list-none flex-wrap items-center gap-1 p-0" aria-label="Chapters">
            {chapters.map((chapter, index) => (
                <li key={chapter.moment.id}>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <button
                                    type="button"
                                    data-quill
                                    aria-label={`Chapter ${index + 1}: ${chapter.moment.title}`}
                                    aria-current={index === activeIndex ? 'step' : undefined}
                                    className={`flex size-6 cursor-pointer items-center justify-center rounded-full border text-xs font-medium tabular-nums transition-colors focus-visible:outline-2 focus-visible:outline-(--ring) ${
                                        index === activeIndex
                                            ? 'border-(--foreground) bg-(--foreground) text-(--background)'
                                            : 'border-(--border) bg-transparent text-(--muted-foreground) hover:border-(--foreground) hover:text-(--foreground)'
                                    }`}
                                    onClick={() => setActiveMoment(chapter.moment.id)}
                                    onMouseEnter={() => setPreviewMoment(chapter.moment.id)}
                                    onMouseLeave={() => setPreviewMoment(null)}
                                    onFocus={() => setPreviewMoment(chapter.moment.id)}
                                    onBlur={() => setPreviewMoment(null)}
                                    data-attr="quill-insight-story-step"
                                />
                            }
                        >
                            {index + 1}
                        </TooltipTrigger>
                        <TooltipContent side="bottom">{chapter.moment.title}</TooltipContent>
                    </Tooltip>
                </li>
            ))}
        </ol>
    )
}
