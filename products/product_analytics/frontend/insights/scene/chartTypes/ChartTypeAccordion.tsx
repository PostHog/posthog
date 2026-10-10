import { useActions, useValues } from 'kea'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { ChartTypeMenu } from './ChartTypeMenu'
import { chartTypeStripLogic } from './chartTypeStripLogic'
import { ChartTypeTile } from './ChartTypeTile'

export function ChartTypeAccordion({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const logic = chartTypeStripLogic(insightProps)
    const { stripState, tiles } = useValues(logic)
    const { selectChartType } = useActions(logic)

    if (stripState === 'hidden') {
        return null
    }

    return (
        <Collapsible variant="folder" className="pb-8" data-attr="quill-insight-chart-type-accordion">
            <CollapsibleTrigger className="w-fit">Suggested ways to view this</CollapsibleTrigger>
            <CollapsibleContent
                className="flex flex-wrap gap-3 pt-2"
                // The section is the last thing on the page, so the tiles open below the fold.
                onTransitionEnd={(event) => {
                    if (event.target === event.currentTarget && event.currentTarget.hasAttribute('data-open')) {
                        event.currentTarget
                            .closest('[data-slot="collapsible"]')
                            ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
                    }
                }}
            >
                {tiles.map((tile) => (
                    <ChartTypeTile
                        key={tile.option.display}
                        tile={tile}
                        loading={stripState === 'loading'}
                        onSelect={() => selectChartType(tile.option.display, 'strip')}
                    />
                ))}
                <ChartTypeMenu
                    insightProps={insightProps}
                    triggerClassName="h-auto min-h-10 w-48 rounded-(--radius-md) border-dashed"
                />
            </CollapsibleContent>
        </Collapsible>
    )
}
