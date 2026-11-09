import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { QuillEditorSelect } from 'products/product_analytics/frontend/insights/editor/QuillEditorSelect'

export type RetentionMeanType = 'simple' | 'weighted'

const MEAN_OPTIONS: { value: RetentionMeanType; label: string; tooltip: string }[] = [
    {
        value: 'simple',
        label: 'simple',
        tooltip:
            'Calculates the average retention rate across all cohorts by giving equal weight to each cohort, regardless of its size.',
    },
    {
        value: 'weighted',
        label: 'weighted',
        tooltip:
            'Calculates the average retention rate by giving more weight to larger cohorts, accounting for different cohort sizes in the final mean.',
    },
]

export function RetentionMeanDropdown(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const currentMean = retentionFilter?.meanRetentionCalculation ?? 'simple'
    const onChange = (meanRetentionCalculation: typeof currentMean): void => {
        updateInsightFilter({ meanRetentionCalculation })
    }

    if (!canEditInsight) {
        return null
    }

    if (quillSurface) {
        return <QuillEditorSelect className="w-48" value={currentMean} onChange={onChange} options={MEAN_OPTIONS} />
    }

    return <LemonSelect className="w-48" size="small" value={currentMean} onChange={onChange} options={MEAN_OPTIONS} />
}
