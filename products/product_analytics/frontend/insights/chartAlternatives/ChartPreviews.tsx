import { useActions, useMountedLogic, useValues } from 'kea'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import type { InsightLogicProps } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import { chartPreviewsLogic, previewVizNode } from './chartPreviewsLogic'
import { ChartPreviewTile } from './ChartPreviewTile'

export function ChartPreviews({
    editMode,
    embedded,
    inSharedMode,
    insightProps,
}: {
    editMode?: boolean
    embedded: boolean
    inSharedMode?: boolean
    insightProps: InsightLogicProps
}): JSX.Element | null {
    const logicProps = { editMode, embedded, inSharedMode, ...insightProps }
    const alternativesLogic = useMountedLogic(chartAlternativesLogic(logicProps))
    const logic = useMountedLogic(chartPreviewsLogic(logicProps))
    const { selectionDisabledReason } = useValues(alternativesLogic)
    const { selectChart } = useActions(alternativesLogic)
    const {
        canShowPreviews,
        freeResponse,
        insightDataLoading,
        moreResponse,
        orderedPreviews,
        otherResponseLoading,
        trendsSource,
    } = useValues(logic)

    if (!canShowPreviews || !trendsSource) {
        return null
    }

    return (
        <div className="rounded border bg-surface-primary p-2" data-attr="chart-previews">
            <ScrollableShadows
                direction="horizontal"
                innerClassName="snap-x snap-mandatory"
                contentClassName="flex gap-2 pb-1"
            >
                {orderedPreviews.map(({ option, needsMore }) => (
                    <ChartPreviewTile
                        key={option.display}
                        uniqueKey={`chart-preview-${logic.key}-${option.display}`}
                        option={option}
                        query={previewVizNode(trendsSource, option.display)}
                        response={needsMore ? moreResponse : freeResponse}
                        loading={needsMore ? otherResponseLoading : insightDataLoading && !freeResponse}
                        disabledReason={selectionDisabledReason}
                        onSelect={() => selectChart(option.display, 'preview')}
                    />
                ))}
            </ScrollableShadows>
        </div>
    )
}
