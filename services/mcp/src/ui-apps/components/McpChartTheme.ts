import type { ChartTheme } from 'lib/charts/types'

/**
 * Static ChartTheme for MCP UI apps.
 *
 * Concrete hex values (not `var(--…)`) because hog-charts draws series on canvas;
 * `ctx.strokeStyle = 'var(--…)'` doesn't resolve and falls back to black. Axis text
 * adapts to dark/light at module load — canvas can't follow CSS vars at runtime.
 *
 * Palette uses PostHog brand colors.
 */

export const MCP_CHART_THEME: ChartTheme = {
    colors: [
        '#1d4aff', // PostHog blue
        '#621da6', // PostHog purple
        '#00d683', // PostHog green
        '#f54e00', // PostHog orange
        '#f7a501', // PostHog yellow
        '#dc2626', // red
    ],
    backgroundColor: '#ffffff',
    // Single mid-gray for axis labels — readable on both light and dark hosts.
    // Claude Desktop's iframe doesn't set `prefers-color-scheme`, so we can't
    // detect host theme and adapt at runtime.
    axisColor: '#9ca3af',
    gridColor: 'rgba(128, 128, 128, 0.2)',
    crosshairColor: 'rgba(128, 128, 128, 0.5)',
    tooltipBackground: '#ffffff',
    tooltipColor: '#111827',
}
