// eslint-disable-next-line @typescript-eslint/no-var-requires
const cyclotron = require('../index.node')

export type CyclotronMetricsConfig = {
    defaultLabels: Record<string, string>,
    histogramBounds: number[],
}

export type CyclotronMetricsReport = {
    measurements: CyclotronMetricsMeasurement[],
}

export type CyclotronMetricsMeasurement = {
    name: string,
    labels: Record<string, string>,
    value: number | [number, number][],
    type: 'counter' | 'gauge' | 'histogram',
}

export function initCyclotronMetrics(config: CyclotronMetricsConfig): void {
    cyclotron.initMetrics(JSON.stringify(config))
}

export function getMetricsReport(): CyclotronMetricsReport {
    // I have no idea how the type checking here works.
    return JSON.parse(cyclotron.getMetricsReport()) as CyclotronMetricsReport
}

// Used for testing
export function emitFakeMetrics(): void {
    cyclotron.emitFakeMetrics()
}