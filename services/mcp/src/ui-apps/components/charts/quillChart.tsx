import type { ReactElement, ReactNode } from 'react'

import type { ChartTheme } from '@posthog/quill-charts'

// Quill charts render on a canvas, so colours must be concrete values — `var(--…)`
// strings don't resolve inside a 2D context. We read the chart palette (and axis/grid
// colours) from the CSS variables declared in `styles/base.css`, which the MCP host can
// override via ext-apps, falling back to the light-mode hexes when computed styles aren't
// available. Reading happens at render (in the browser), never at module load.
const FALLBACK_COLORS = ['#1d4aff', '#621da6', '#42827e', '#ce0e74', '#f14f58', '#7c440e', '#529a0a', '#0476fb']

function readVar(styles: CSSStyleDeclaration, name: string, fallback: string): string {
    return styles.getPropertyValue(name).trim() || fallback
}

export function buildMcpChartTheme(): ChartTheme {
    if (typeof window === 'undefined' || typeof getComputedStyle !== 'function') {
        return { colors: FALLBACK_COLORS, backgroundColor: '#ffffff' }
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

const FRAME_HEIGHT = 400

interface ChartFrameProps {
    children: ReactNode
    labels: string[]
    colors: string[]
    showLegend?: boolean
}

// Fixed-height flex column so the canvas chart (whose root is `flex: 1`) gets a concrete
// size for its ResizeObserver, with an inline-styled legend below. We render the legend
// ourselves rather than using Quill's `ChartLegend` to keep the swatch styling independent
// of which Tailwind utilities get generated for the MCP bundle.
export function ChartFrame({ children, labels, colors, showLegend = true }: ChartFrameProps): ReactElement {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: FRAME_HEIGHT }}>
            {children}
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
