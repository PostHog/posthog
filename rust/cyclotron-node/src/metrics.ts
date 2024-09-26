// eslint-disable-next-line @typescript-eslint/no-var-requires
const cyclotron = require('../index.node')

export type CyclotronMetricsConfig = {
    defaultLabels: Map<string, string>
}

export type CyclotronMetricsReport = {
    measurements: CyclotronMetricsMeasurement[],
}

export type CyclotronMetricsMeasurement = {
    name: string,
    labels: Map<string, string>,
    value: number | number[],
    type: 'counter' | 'gauge' | 'histogram',
}

export function initCyclotronMetrics(config: CyclotronMetricsConfig): void {
    cyclotron.initMetrics(JSON.stringify(config))
}

export function getMetricsReport(): CyclotronMetricsReport {
    return JSON.parse(cyclotron.getMetricsReport()) as CyclotronMetricsReport
}

// Used for testing
export function emitFakeMetrics(): void {
    cyclotron.emitFakeMetrics()
}