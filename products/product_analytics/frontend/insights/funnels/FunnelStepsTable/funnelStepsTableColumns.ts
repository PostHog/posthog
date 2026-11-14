export type FunnelStepMetric =
    | 'conversion'
    | 'dropoff'
    | 'conversion_so_far'
    | 'conversion_from_prev'
    | 'median_time'
    | 'average_time'

export interface FunnelStepColumn {
    key: string
    metric: FunnelStepMetric
    title: string
}

const FIRST_STEP_METRICS: FunnelStepMetric[] = ['conversion', 'conversion_so_far']
const LATER_STEP_METRICS: FunnelStepMetric[] = [
    'conversion',
    'dropoff',
    'conversion_so_far',
    'conversion_from_prev',
    'median_time',
    'average_time',
]

const TITLES: Record<FunnelStepMetric, string> = {
    conversion: 'Converted',
    dropoff: 'Dropped off',
    conversion_so_far: 'Conversion so far',
    conversion_from_prev: 'Conversion from previous',
    median_time: 'Median time',
    average_time: 'Average time',
}

export function funnelStepColumns(stepIndex: number): FunnelStepColumn[] {
    return (stepIndex === 0 ? FIRST_STEP_METRICS : LATER_STEP_METRICS).map((metric) => ({
        // pinned: funnelDataLogic sorts by this key, and a saved query stores it in `breakdownSorting`
        key: `step_${stepIndex}_${metric}`,
        metric,
        title: stepIndex === 0 && metric === 'conversion' ? 'Entered' : TITLES[metric],
    }))
}
