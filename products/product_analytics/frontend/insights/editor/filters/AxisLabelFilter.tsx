import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'
import { normalizeAxisLabel } from '@posthog/quill-charts'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function AxisLabelFilter({ axis }: { axis: 'x' | 'y' }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const savedLabel = axis === 'x' ? trendsFilter?.xAxisLabel : trendsFilter?.yAxisLabel
    const [draft, setDraft] = useState(savedLabel ?? '')

    useEffect(() => {
        setDraft(savedLabel ?? '')
    }, [savedLabel])

    const commit = (): void => {
        const normalized = normalizeAxisLabel(draft)
        setDraft(normalized ?? '')
        updateInsightFilter(axis === 'x' ? { xAxisLabel: normalized } : { yAxisLabel: normalized })
    }

    return (
        <div className="flex p-1 px-2">
            <LemonInput
                size="small"
                className="w-0 flex-1"
                data-attr={`trends-${axis}-axis-label-input`}
                value={draft}
                placeholder="Label"
                onChange={setDraft}
                onBlur={commit}
                onPressEnter={commit}
            />
        </div>
    )
}
