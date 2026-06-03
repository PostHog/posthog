import type { ReactElement, ReactNode } from 'react'

import type { ChartTheme, XAxisConfig, YAxisConfig, YAxisFormat } from '@posthog/quill-charts'

import type { TrendsInterval } from '../types'
import { formatDate } from '../utils'

// These charts render on a canvas, so colours must be concrete values — `var(--…)`
// strings don't resolve inside a 2D context. We read the chart palette (and axis/grid
// colours) from the CSS variables declared in `styles/base.css`, which the MCP host can
// override via ext-apps, falling back to the light-mode hexes when computed styles aren't
// available. Reading happens at render (in the browser), never at module load.
export const DEFAULT_CHART_COLOR = '#1d4aff'
export const DEFAULT_CURRENCY = 'USD'
const FALLBACK_COLORS = [
    DEFAULT_CHART_COLOR,
    '#621da6',
    '#42827e',
    '#ce0e74',
    '#f14f58',
    '#7c440e',
    '#529a0a',
    '#0476fb',
]

function readVar(styles: CSSStyleDeclaration, name: string, fallback: string): string {
    return styles.getPropertyValue(name).trim() || fallback
}

export function buildMcpChartTheme(): ChartTheme {
    if (typeof window === 'undefined' || typeof getComputedStyle !== 'function') {
        return {
            colors: FALLBACK_COLORS,
            backgroundColor: '#ffffff',
            axisColor: '#6b7280',
            gridColor: '#e5e7eb',
            crosshairColor: 'rgba(128, 128, 128, 0.5)',
            tooltipBackground: '#f9fafb',
            tooltipColor: '#101828',
        }
    }
    const styles = getComputedStyle(document.documentElement)
    return {
        colors: FALLBACK_COLORS.map((fallback, i) => readVar(styles, `--posthog-chart-${i + 1}`, fallback)),
        backgroundColor: readVar(styles, '--color-background-primary', '#ffffff'),
        axisColor: readVar(styles, '--color-text-secondary', '#6b7280'),
        gridColor: readVar(styles, '--color-border-primary', '#e5e7eb'),
        crosshairColor: 'rgba(128, 128, 128, 0.5)',
        tooltipBackground: readVar(styles, '--color-background-secondary', '#f9fafb'),
        tooltipColor: readVar(styles, '--color-text-primary', '#101828'),
    }
}

// Palette colour for the series at `index`, wrapping the (guaranteed non-empty) theme palette.
export function mcpSeriesColor(theme: ChartTheme, index: number): string {
    return theme.colors[index % theme.colors.length] ?? DEFAULT_CHART_COLOR
}

// Interval-aware x-axis when the query carries interval + timezone (lets the chart format ticks
// itself); otherwise fall back to pretty-printing whatever date-like labels we were handed.
export function buildMcpXAxis(interval: TrendsInterval | undefined, timezone: string | undefined): XAxisConfig {
    return interval && timezone ? { interval, timezone } : { tickFormatter: formatDate }
}

export function buildMcpYAxis(yUnit: YAxisFormat): YAxisConfig {
    return {
        format: yUnit,
        ...(yUnit === 'currency' ? { currency: DEFAULT_CURRENCY } : {}),
        showGrid: true,
    }
}

const CHART_HEIGHT = 400

interface ChartFrameProps {
    children: ReactNode
    labels: string[]
    colors: string[]
    showLegend?: boolean
}

// Gives the canvas chart a concrete `CHART_HEIGHT` (its root is `flex: 1` and needs a sized
// parent for its ResizeObserver), then lets the column grow to fit the legend below — so a
// multi-series chart keeps its full height instead of ceding it to the legend. We render the
// legend ourselves rather than using the chart library's `ChartLegend` to keep the swatch
// styling independent of which Tailwind utilities get generated for the MCP bundle.
export function ChartFrame({ children, labels, colors, showLegend = true }: ChartFrameProps): ReactElement {
    return (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', height: CHART_HEIGHT }}>{children}</div>
            {showLegend && labels.length > 1 && (
                <div
                    style={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: '1rem',
                        justifyContent: 'center',
                        marginTop: '0.5rem',
                        fontSize: '0.75rem',
                    }}
                >
                    {labels.map((label, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                            <div
                                style={{
                                    width: '12px',
                                    height: '12px',
                                    borderRadius: '2px',
                                    backgroundColor: colors[i % colors.length],
                                }}
                            />
                            <span style={{ color: 'var(--color-text-secondary, #6b7280)' }}>{label}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
