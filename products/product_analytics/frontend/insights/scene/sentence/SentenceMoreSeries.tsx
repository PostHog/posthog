import { useActions, useValues } from 'kea'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { EditableWord } from './EditableWord'
import { insightSentenceLogic } from './insightSentenceLogic'

/** Stands for the events the sentence does not name. Hovering lists them, and a click gives each one a line. */
export function SentenceMoreSeries({
    insightProps,
    label,
}: {
    insightProps: InsightLogicProps
    label: string
}): JSX.Element {
    const { collapsedSeriesLabels } = useValues(insightSentenceLogic(insightProps))
    const { setSeriesExpanded } = useActions(insightSentenceLogic(insightProps))

    return (
        <Tooltip>
            <TooltipTrigger
                delay={150}
                render={
                    <EditableWord
                        color="blue"
                        aria-expanded={false}
                        onClick={() => setSeriesExpanded(true)}
                        data-attr="quill-insight-sentence-more-series"
                    />
                }
            >
                {label}
            </TooltipTrigger>
            <TooltipContent>
                <ul className="m-0 flex list-none flex-col gap-1 p-0">
                    {collapsedSeriesLabels.map((seriesLabel, index) => (
                        <li key={index}>{seriesLabel}</li>
                    ))}
                </ul>
            </TooltipContent>
        </Tooltip>
    )
}
