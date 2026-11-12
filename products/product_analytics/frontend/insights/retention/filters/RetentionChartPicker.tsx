import { useActions, useValues } from 'kea'

import { IconGraph, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'

function ChartFilterOptionLabel(props: { label: string; description?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-[2px]">
            <span>{props.label}</span>
            <span className="text-xs text-tertiary font-normal">{props.description}</span>
        </div>
    )
}

export const RETENTION_CHART_GROUP_TITLE = 'Time series'

export const RETENTION_CHART_OPTIONS: {
    value: ChartDisplayType
    icon: JSX.Element
    label: string
    description: string
}[] = [
    {
        value: ChartDisplayType.ActionsLineGraph,
        icon: <IconTrends />,
        label: 'Line chart',
        description: 'Retention over time plotted as a continuous line for each cohort.',
    },
    {
        value: ChartDisplayType.ActionsBar,
        icon: <IconGraph />,
        label: 'Bar chart',
        description: 'Retention over time as vertical bars for each cohort.',
    },
]

const OPTIONS: LemonSelectOptions<ChartDisplayType> = [
    {
        title: RETENTION_CHART_GROUP_TITLE,
        options: RETENTION_CHART_OPTIONS.map(({ value, icon, label, description }) => ({
            value,
            icon,
            label,
            labelInMenu: <ChartFilterOptionLabel label={label} description={description} />,
        })),
    },
]

export function RetentionChartPicker({
    fullWidth = false,
    disabledReason,
    onSelect,
}: {
    fullWidth?: boolean
    disabledReason?: string
    onSelect?: (display: ChartDisplayType) => void
}): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const selectChart = (value: ChartDisplayType): void => {
        updateInsightFilter({ display: value })
    }

    return (
        <LemonSelect
            key="2"
            value={retentionFilter?.display || ChartDisplayType.ActionsLineGraph}
            onChange={onSelect ? undefined : selectChart}
            onSelect={onSelect}
            dropdownPlacement="bottom-end"
            optionTooltipPlacement="left"
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            options={OPTIONS}
            size="small"
            fullWidth={fullWidth}
            disabledReason={editingDisabledReason ?? disabledReason}
        />
    )
}
