import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { LemonInput, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { QuillDisplayOptionNumberInput } from '~/queries/nodes/InsightViz/QuillDisplayOptionNumberInput'
import { isTrendsQuery } from '~/queries/utils'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

const CONFIDENCE_LEVEL_INFO =
    'A 95% confidence level means that for each data point, we are 95% confident that the true value is within the confidence interval.'

export function ConfidenceLevelInput(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { confidenceLevel, showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const trendsFilter = isTrendsQuery(querySource) ? querySource.trendsFilter : undefined

    const [localValue, setLocalValue] = useState(confidenceLevel)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(() => {
        setLocalValue(confidenceLevel)
    }, [confidenceLevel])

    const debouncedUpdate = useDebouncedCallback((value: number) => {
        if (isTrendsQuery(querySource)) {
            const newQuery = { ...querySource }
            newQuery.trendsFilter = { ...trendsFilter, confidenceLevel: value }
            updateQuerySource(newQuery)
        }
    }, 500)

    const disabledReason = !showConfidenceIntervals
        ? 'Confidence intervals are only available for line graphs'
        : undefined
    const onValueChange = (value: number | undefined): void => {
        const numValue = value ?? 95
        setLocalValue(numValue)
        debouncedUpdate(numValue)
    }

    if (todayRailNav) {
        return (
            <QuillDisplayOptionNumberInput
                label="Confidence level"
                info={CONFIDENCE_LEVEL_INFO}
                value={localValue}
                onChange={onValueChange}
                onCommit={() => debouncedUpdate.flush()}
                min={0}
                max={100}
                suffix="%"
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <div className="flex items-center justify-between w-full px-2 pb-2 pl-4">
            <Tooltip title={CONFIDENCE_LEVEL_INFO}>
                <span>Confidence level</span>
            </Tooltip>
            <LemonInput
                type="number"
                className="w-20"
                value={localValue}
                onChange={onValueChange}
                onBlur={() => debouncedUpdate.flush()}
                min={0}
                max={100}
                step={1}
                suffix={<span>%</span>}
                disabledReason={disabledReason}
            />
        </div>
    )
}
