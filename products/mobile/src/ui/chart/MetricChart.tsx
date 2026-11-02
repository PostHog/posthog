import type { ReactElement } from 'react'

import { useCanvasSlot } from './budget/ChartCanvasBudget'
import { MetricChartCanvas } from './MetricChartCanvas'
import { MetricChartPlaceholder } from './MetricChartPlaceholder'
import type { MetricChartProps } from './types'

export function MetricChart(props: MetricChartProps): ReactElement {
    const mounted = useCanvasSlot(props.canvasSlot)
    return mounted ? <MetricChartCanvas {...props} /> : <MetricChartPlaceholder {...props} />
}
