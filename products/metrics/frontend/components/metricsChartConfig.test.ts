import type { XAxisConfig } from '@posthog/quill-charts'

import type { MetricsDisplaySettings } from '~/queries/schema/schema-general'

import { buildMetricsChartConfig, metricsBarValueDomain } from './metricsChartConfig'

const X_AXIS: XAxisConfig = {}

const build = (
    display: MetricsDisplaySettings | undefined,
    seriesCount = 1
): ReturnType<typeof buildMetricsChartConfig> =>
    buildMetricsChartConfig({ display, xAxis: X_AXIS, seriesCount, labelFormatter: (l) => l })

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

    it.each([
        ['both bounds', { min: 10, max: 100 }, { min: 10, max: 100 }],
        ['max only', { max: 100 }, { max: 100 }],
        ['scale without bounds', { scale: 'log' as const }, undefined],
        ['no settings', undefined, undefined],
    ])('derives the bar value domain from %s', (_name, yAxis, expected) => {
        // Bars ignore `YAxisConfig.min`/`max`, so without this the range control no-ops on bars.
        expect(metricsBarValueDomain(yAxis)).toEqual(expected)
    })

    it('only shows the legend once there is more than one series', () => {
        expect(build(undefined, 1).legend).toMatchObject({ show: false })
        expect(build(undefined, 2).legend).toMatchObject({ show: true })
    })
})
