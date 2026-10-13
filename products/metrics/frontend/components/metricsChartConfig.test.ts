import type { XAxisConfig, YAxisConfig } from '@posthog/quill-charts'

import type { MetricsDisplaySettings } from '~/queries/schema/schema-general'

import { buildMetricsChartConfig } from './metricsChartConfig'

const X_AXIS: XAxisConfig = {}

const build = (
    display: MetricsDisplaySettings | undefined,
    seriesCount = 1,
    unit?: string
): ReturnType<typeof buildMetricsChartConfig> =>
    buildMetricsChartConfig({ display, xAxis: X_AXIS, seriesCount, labelFormatter: (l) => l, unit })

describe('metricsChartConfig', () => {
    it('omits the settings keys entirely when a query carries no display', () => {
        const config = build(undefined)

        // Not `toBeUndefined()`: `useChartConfig` spreads quill's defaults under whatever keys are
        // present, so an explicitly-undefined key would override them and change existing charts.
        expect(config).not.toHaveProperty('yAxis')
        expect(config).not.toHaveProperty('goalLines')
    })

    it('renames goal line fields onto the quill config', () => {
        const config = build({
            goalLines: [{ label: 'SLO', value: 99.9, borderColor: '#ff0000', position: 'start' }],
        })

        expect(config.goalLines).toEqual([
            {
                value: 99.9,
                label: 'SLO',
                color: '#ff0000',
                labelPosition: 'start',
                displayLabel: undefined,
                displayIfCrossed: undefined,
            },
        ])
    })

    it('maps y-axis settings and keeps unset bounds off the config', () => {
        const config = build({ yAxis: { scale: 'log', startAtZero: false, max: 100 } })

        expect(config.yAxis).toEqual({ scale: 'log', startAtZero: false, max: 100 })
    })

    it('formats axis ticks and tooltip values with the unit and keeps the y-axis settings', () => {
        const config = build({ yAxis: { scale: 'log' } }, 1, 'ms')
        const yAxis = config.yAxis as YAxisConfig

        expect(yAxis.scale).toBe('log')
        expect(yAxis.tickFormatter?.(250)).toBe('250 ms')
        expect(config.tooltip?.valueFormatter?.(1500, {} as never)).toBe('1.5 s')
    })

    it('only shows the legend once there is more than one series', () => {
        expect(build(undefined, 1).legend).toMatchObject({ show: false })
        expect(build(undefined, 2).legend).toMatchObject({ show: true })
    })
})
