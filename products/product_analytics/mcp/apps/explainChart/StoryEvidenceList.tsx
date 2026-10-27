import { ArrowUpRight } from 'lucide-react'
import { type ReactElement } from 'react'

import { Button, Text } from '@posthog/quill'

import type { StoryEvidence } from './explainChartTypes'
import { StoryMarkedText } from './StoryMarkedText'

export interface StoryEvidenceListProps {
    evidence: StoryEvidence[]
    openLink: (url: string) => void
    canShowChart: (item: StoryEvidence) => boolean
    shownIndex: number | null
    onToggleChart: (index: number) => void
}

export function StoryEvidenceList({
    evidence,
    openLink,
    canShowChart,
    shownIndex,
    onToggleChart,
}: StoryEvidenceListProps): ReactElement | null {
    if (!evidence.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-1.5" data-attr="explain-chart-evidence">
            <Text size="xs" weight="medium" variant="muted">
                Evidence
            </Text>
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
                {evidence.map((item, index) => (
                    <li
                        key={index}
                        className={`-mx-2 flex items-start gap-2 rounded-md px-2 py-1 ${
                            index === shownIndex ? 'bg-muted' : ''
                        }`}
                    >
                        <span
                            className={`mt-2 size-1.5 shrink-0 rounded-full ${
                                index === shownIndex ? 'bg-(--primary-light)' : 'bg-muted-foreground'
                            }`}
                            aria-hidden
                        />
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <Text size="sm">
                                <StoryMarkedText text={item.text} />
                            </Text>
                            {(canShowChart(item) || item.url) && (
                                <div className="flex flex-wrap items-center gap-3">
                                    {canShowChart(item) && (
                                        <Button
                                            variant="link"
                                            size="xs"
                                            className="h-auto p-0"
                                            aria-pressed={index === shownIndex}
                                            onClick={() => onToggleChart(index)}
                                            data-attr="explain-chart-evidence-chart"
                                        >
                                            {index === shownIndex ? 'Hide chart' : 'Show chart'}
                                        </Button>
                                    )}
                                    {item.url && (
                                        <Button
                                            variant="link"
                                            size="xs"
                                            className="h-auto p-0"
                                            onClick={() => item.url && openLink(item.url)}
                                            data-attr="explain-chart-evidence-link"
                                        >
                                            Open in PostHog
                                            <ArrowUpRight className="size-3" />
                                        </Button>
                                    )}
                                </div>
                            )}
                        </div>
                    </li>
                ))}
            </ul>
        </div>
    )
}
