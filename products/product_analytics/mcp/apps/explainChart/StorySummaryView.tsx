import { type ReactElement } from 'react'

import { Text } from '@posthog/quill'

import { StoryMarkedText } from './StoryMarkedText'
import type { StoryPage } from './storyPages'

export interface StorySummaryViewProps {
    headline: string
    pages: StoryPage[]
    /** Which series the story follows, when the chart has more than one. */
    seriesNote: string | null
    warnings?: string[]
    onSelect: (index: number) => void
    onPreview: (index: number | null) => void
}

export function StorySummaryView({
    headline,
    pages,
    seriesNote,
    warnings = [],
    onSelect,
    onPreview,
}: StorySummaryViewProps): ReactElement {
    const [summary, ...chapters] = pages
    return (
        <div
            className="grid gap-4 transition-opacity duration-300 motion-reduce:transition-none starting:opacity-0 @xl/story:grid-cols-2 @3xl/story:grid-cols-1"
            data-attr="explain-chart-summary"
        >
            <div className="flex flex-col gap-2">
                <Text size="xs" variant="muted">
                    Summary
                </Text>
                <Text size="base" weight="medium">
                    <StoryMarkedText text={headline} />
                </Text>
                {summary?.facts && (
                    <Text size="sm">
                        <StoryMarkedText text={summary.facts} />
                    </Text>
                )}
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
            {chapters.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <Text size="xs" weight="medium" variant="muted">
                        What stands out
                    </Text>
                    <ol className="-mx-2 my-0 flex list-none flex-col p-0">
                        {chapters.map((page, offset) => {
                            const index = offset + 1
                            return (
                                <li key={index}>
                                    <button
                                        type="button"
                                        className="flex w-full cursor-pointer items-center gap-2.5 rounded-md border-0 bg-transparent px-2 py-1.5 text-start hover:bg-fill-hover focus-visible:outline-2 focus-visible:outline-ring"
                                        onClick={() => onSelect(index)}
                                        onMouseEnter={() => onPreview(index)}
                                        onMouseLeave={() => onPreview(null)}
                                        onFocus={() => onPreview(index)}
                                        onBlur={() => onPreview(null)}
                                        data-attr="explain-chart-contents-item"
                                    >
                                        <span className="flex size-5 shrink-0 items-center justify-center rounded-full border border-border text-xs font-medium tabular-nums text-muted-foreground">
                                            {index}
                                        </span>
                                        <Text size="sm" className="min-w-0 [overflow-wrap:anywhere]" render={<span />}>
                                            {page.title}
                                        </Text>
                                    </button>
                                </li>
                            )
                        })}
                    </ol>
                </div>
            )}
        </div>
    )
}
