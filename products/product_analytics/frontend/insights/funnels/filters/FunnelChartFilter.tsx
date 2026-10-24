import { useActions, useValues } from 'kea'

import { IconClock, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptionLeaf, LemonSelectOptions } from '@posthog/lemon-ui'

import { FunnelLayout } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFunnelHorizontal, IconFunnelVertical, IconTrendingUp } from 'lib/lemon-ui/icons'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { FunnelVizType } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'

type FunnelChartType = 'steps-vertical' | 'steps-horizontal' | 'time-to-convert' | 'trends' | 'trends-metric'

const CHART_TYPE_FILTERS: Record<FunnelChartType, Pick<FunnelsFilter, 'funnelVizType' | 'layout'>> = {
    'steps-vertical': { funnelVizType: FunnelVizType.Steps, layout: FunnelLayout.vertical },
    'steps-horizontal': { funnelVizType: FunnelVizType.Steps, layout: FunnelLayout.horizontal },
    'time-to-convert': { funnelVizType: FunnelVizType.TimeToConvert },
    trends: { funnelVizType: FunnelVizType.Trends },
    'trends-metric': { funnelVizType: FunnelVizType.Trends, layout: FunnelLayout.metric },
}

function currentChartType({ funnelVizType, layout }: FunnelsFilter): FunnelChartType {
    if (funnelVizType === FunnelVizType.TimeToConvert) {
        return 'time-to-convert'
    }
    if (funnelVizType === FunnelVizType.Trends) {
        return layout === FunnelLayout.metric ? 'trends-metric' : 'trends'
    }
    return layout === FunnelLayout.horizontal ? 'steps-horizontal' : 'steps-vertical'
}

function OptionLabel({ label, description }: { label: string; description: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-[2px]">
            <span>{label}</span>
            <span className="text-xs text-tertiary font-normal">{description}</span>
        </div>
    )
}

function option(
    value: FunnelChartType,
    icon: JSX.Element,
    label: string,
    description: string
): LemonSelectOptionLeaf<FunnelChartType> {
    return { value, icon, label, labelInMenu: <OptionLabel label={label} description={description} /> }
}

export function FunnelChartFilter(): JSX.Element | null {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { funnelsFilter, aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const hasMetricInsight = useFeatureFlag('METRIC_INSIGHT')

    if (funnelsFilter?.funnelVizType === FunnelVizType.Flow) {
        return null
    }

    const options: LemonSelectOptions<FunnelChartType> = [
        {
            title: 'Conversion steps',
            options: [
                option(
                    'steps-vertical',
                    <IconFunnelVertical />,
                    'Left to right',
                    'Each step is a bar, from left to right.'
                ),
                option(
                    'steps-horizontal',
                    <IconFunnelHorizontal />,
                    'Top to bottom',
                    'Each step is a bar, from top to bottom.'
                ),
            ],
        },
        {
            title: 'Conversion time',
            options: [
                option(
                    'time-to-convert',
                    <IconClock />,
                    'Time to convert',
                    `Track how long it takes for ${aggregationTargetLabel.plural} to convert.`
                ),
            ],
        },
        {
            title: 'Conversion rate over time',
            options: [
                option(
                    'trends',
                    <IconTrends />,
                    'Historical trends',
                    "Track how this funnel's conversion rate is trending over time."
                ),
                ...(hasMetricInsight || funnelsFilter?.layout === FunnelLayout.metric
                    ? [
                          option(
                              'trends-metric',
                              <IconTrendingUp />,
                              'Metric',
                              'The average conversion rate, with a sparkline and the change from the previous period.'
                          ),
                      ]
                    : []),
            ],
        },
    ]

    return (
        <LemonSelect
            value={currentChartType(funnelsFilter ?? {})}
            onChange={(value) => {
                const { funnelVizType, layout } = CHART_TYPE_FILTERS[value]
                // Keep the steps layout across viz types, but the metric layout only applies to trends.
                const keptLayout = funnelsFilter?.layout === FunnelLayout.metric ? undefined : funnelsFilter?.layout
                updateInsightFilter({ funnelVizType, layout: layout ?? keptLayout })
            }}
            dropdownPlacement="bottom-end"
            dropdownMatchSelectWidth={false}
            data-attr="funnel-viz-type-select"
            options={options}
            size="small"
            disabledReason={editingDisabledReason}
        />
    )
}
