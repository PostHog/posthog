import { createRoot } from 'react-dom/client'

import {
    BarChart,
    ChartLegend,
    createXAxisTickCallback,
    legendItemsFromSeries,
    TimeSeriesLineChart,
} from '@posthog/quill-charts'

// Mirrors services/mcp/src/ui-apps/components/charts/theme.ts, so terminal charts match the MCP charts.
const THEME = {
    colors: [
        '#1d4aff',
        '#621da6',
        '#42827e',
        '#ce0e74',
        '#f14f58',
        '#7c440e',
        '#529a0a',
        '#0476fb',
        '#fe729e',
        '#35416b',
    ],
    backgroundColor: '#ffffff',
    axisColor: '#6b7280',
    gridColor: 'rgba(128, 128, 128, 0.2)',
    crosshairColor: 'rgba(128, 128, 128, 0.5)',
    tooltipBackground: '#ffffff',
    tooltipColor: '#111827',
}

const { title, subtitle, kind, x, series, unit, timezone = 'UTC' } = window.SPEC
const data = series.map((s, i) => ({ key: String(i), label: s.name, data: s.values.map((v) => v ?? NaN) }))

createRoot(document.getElementById('root')).render(
    <>
        {subtitle && <div className="subtitle">{subtitle}</div>}
        <h1>{title}</h1>
        {/* ChartLegend renders bare children when hidden, so the height lives on this wrapper. */}
        <div className="chart">
            <ChartLegend show={data.length > 1} items={legendItemsFromSeries(data, THEME)} position="bottom">
                {kind === 'bar' ? (
                    <BarChart
                        labels={x}
                        series={data}
                        theme={THEME}
                        config={{
                            showGrid: true,
                            barLayout: 'grouped',
                            yTickFormatter: (v) => `${v.toLocaleString('en-US')}${unit ?? ''}`,
                        }}
                    />
                ) : (
                    <TimeSeriesLineChart
                        labels={x}
                        series={data}
                        theme={THEME}
                        config={{
                            xAxis: { tickFormatter: createXAxisTickCallback({ allDays: x, timezone }) },
                            yAxis: { showGrid: true, suffix: unit },
                        }}
                    />
                )}
            </ChartLegend>
        </div>
    </>
)
