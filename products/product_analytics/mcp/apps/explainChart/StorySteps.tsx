import { House } from 'lucide-react'
import { type ReactElement } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { StoryPage } from './storyPages'

export interface StoryStepsProps {
    pages: StoryPage[]
    activeIndex: number
    onSelect: (index: number) => void
    onPreview: (index: number | null) => void
}

export function StorySteps({ pages, activeIndex, onSelect, onPreview }: StoryStepsProps): ReactElement {
    return (
        <ol className="m-0 flex list-none flex-wrap items-center gap-1 p-0" aria-label="Chapters">
            {pages.map((page, index) => (
                <li key={index}>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <button
                                    type="button"
                                    aria-label={index === 0 ? page.title : `Chapter ${index}: ${page.title}`}
                                    aria-current={index === activeIndex ? 'step' : undefined}
                                    className={`flex size-6 cursor-pointer items-center justify-center rounded-full border text-xs font-medium tabular-nums transition-colors focus-visible:outline-2 focus-visible:outline-ring ${
                                        index === activeIndex
                                            ? 'border-foreground bg-foreground text-background'
                                            : 'border-border bg-transparent text-muted-foreground hover:border-foreground hover:text-foreground'
                                    }`}
                                    onClick={() => onSelect(index)}
                                    onMouseEnter={() => onPreview(index)}
                                    onMouseLeave={() => onPreview(null)}
                                    onFocus={() => onPreview(index)}
                                    onBlur={() => onPreview(null)}
                                    data-attr="explain-chart-step"
                                />
                            }
                        >
                            {index === 0 ? <House className="size-3" /> : index}
                        </TooltipTrigger>
                        <TooltipContent side="bottom">{page.title}</TooltipContent>
                    </Tooltip>
                </li>
            ))}
        </ol>
    )
}
