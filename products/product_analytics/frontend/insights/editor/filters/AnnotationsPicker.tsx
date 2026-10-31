import { useActions, useValues } from 'kea'

import { ChartOptionChoice, ChartOptionSelect } from 'lib/components/ChartOptions/ChartOptionSelect'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { AnnotationScope } from '~/types'

import { annotationScopeToName } from 'products/annotations/frontend/logics/annotationModalLogic'

type AnnotationsSelection = AnnotationScope | 'all' | 'none'

const OPTIONS: ChartOptionChoice<AnnotationsSelection>[] = [
    { value: 'all', label: 'All' },
    { value: 'none', label: 'None' },
    ...Object.values(AnnotationScope).map((scope) => ({
        value: scope,
        label: annotationScopeToName[scope],
    })),
]

export function AnnotationsPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showAnnotations, annotationsScope } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <ChartOptionSelect
            value={showAnnotations === false ? 'none' : (annotationsScope ?? 'all')}
            options={OPTIONS}
            onChange={(selection) =>
                updateInsightFilter({
                    showAnnotations: selection === 'none' ? false : undefined,
                    annotationsScope: selection === 'all' || selection === 'none' ? undefined : selection,
                })
            }
            data-attr="insight-annotations-picker"
        />
    )
}
