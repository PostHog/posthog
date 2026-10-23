import { useActions, useValues } from 'kea'

import { IconTrends } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { FunnelLayout } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Icon123, IconFunnelHorizontal, IconFunnelVertical, IconTrendingUp } from 'lib/lemon-ui/icons'
import { insightLogic } from 'scenes/insights/insightLogic'

import { funnelDataLogic } from '../funnelDataLogic'

export function FunnelDisplayLayoutPicker(): JSX.Element | null {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { funnelsFilter, isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const hasMetricInsight = useFeatureFlag('METRIC_INSIGHT')

    if (isTrendsFunnel && !hasMetricInsight) {
        return null
    }

    const options = [
        {
            title: 'Graph Display Options',
            options: isTrendsFunnel
                ? [
                      // The trends viz ignores the steps layouts, so `vertical` stands for the default line chart.
                      { value: FunnelLayout.vertical, icon: <IconTrends />, label: 'Line chart' },
                      { value: FunnelLayout.metric, icon: <IconTrendingUp />, label: 'Metric' },
                  ]
                : [
                      { value: FunnelLayout.vertical, icon: <IconFunnelVertical />, label: 'Left to right' },
                      { value: FunnelLayout.horizontal, icon: <IconFunnelHorizontal />, label: 'Top to bottom' },
                      { value: FunnelLayout.number, icon: <Icon123 />, label: 'Big number' },
                  ],
        },
    ]
    const layout = funnelsFilter?.layout
    const value = isTrendsFunnel && layout !== FunnelLayout.metric ? FunnelLayout.vertical : layout

    return (
        <LemonSelect
            value={value || FunnelLayout.vertical}
            onChange={(layout: FunnelLayout | null) => layout && updateInsightFilter({ layout })}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-bar-layout-selector"
            options={options}
            size="small"
            disabledReason={editingDisabledReason}
        />
    )
}
