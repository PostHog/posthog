import type { ReactElement } from 'react'

import { useTheme } from '@/ui/theme'

import { chartSeriesOf, isCompareSeries } from './chartSeries'
import { Sparkline } from './Sparkline'
import type { MetricChartProps } from './types'
import { chartHeight } from './variant'

/** Stands in for a chart without a canvas, at the same height, so the list does not jump when the canvas mounts. */
export function MetricChartPlaceholder(props: MetricChartProps): ReactElement {
    const theme = useTheme()
    const primary = chartSeriesOf(props, theme).find((s) => !isCompareSeries(s))
    return (
        <Sparkline
            values={primary ? primary.points.map((point) => point.value) : []}
            color={primary?.color}
            width="100%"
            height={chartHeight(props.variant ?? 'inline', props.height)}
            showDot={false}
            testID={props.testID ? `${props.testID}-placeholder` : undefined}
        />
    )
}
