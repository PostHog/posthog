import type { ReactElement } from 'react'

import { MetricChartCanvas } from './MetricChartCanvas'
import type { MetricChartProps } from './types'

export function MetricChart(props: MetricChartProps): ReactElement {
    return <MetricChartCanvas {...props} />
}
