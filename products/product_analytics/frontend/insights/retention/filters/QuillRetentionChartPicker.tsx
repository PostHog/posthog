import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'

import { QuillToolbarSelect } from 'products/product_analytics/frontend/insights/shared/QuillToolbarSelect'

import { RETENTION_CHART_GROUP_TITLE, RETENTION_CHART_OPTIONS } from './RetentionChartPicker'

export function QuillRetentionChartPicker(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <QuillToolbarSelect
            value={retentionFilter?.display || ChartDisplayType.ActionsLineGraph}
            onChange={(display) => updateInsightFilter({ display })}
            options={RETENTION_CHART_OPTIONS}
            groupLabel={RETENTION_CHART_GROUP_TITLE}
            align="end"
            data-attr="chart-filter"
            disabledReason={editingDisabledReason}
        />
    )
}
