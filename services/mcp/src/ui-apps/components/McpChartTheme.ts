import type { ChartTheme } from 'lib/charts/types'

/**
 * Static ChartTheme for MCP UI apps.
 *
 * IIFE-safe: no `getComputedStyle`, no imports from `lib/colors` or
 * `lib/charts/utils/theme` (those read `document.body` at module load).
 * Uses `var(--…)` with hex fallbacks so dark/light mode follows the host
 * CSS variables when present and degrades gracefully when they aren't.
 *
 * Color palette mirrors the existing MCP SVG `LineChart.tsx` exactly so the
 * hog-charts swap is a like-for-like visual change.
 */
export const MCP_CHART_THEME: ChartTheme = {
    colors: [
        'var(--posthog-chart-1, #1d4ed8)',
        'var(--posthog-chart-2, #7c3aed)',
        'var(--posthog-chart-3, #059669)',
        'var(--posthog-chart-4, #dc2626)',
        'var(--posthog-chart-5, #ea580c)',
    ],
    backgroundColor: 'var(--color-bg-primary, #ffffff)',
    axisColor: 'var(--color-text-secondary, #6b7280)',
    gridColor: 'var(--color-border-primary, #e5e7eb)',
    crosshairColor: 'var(--color-border-primary, #e5e7eb)',
    tooltipBackground: 'var(--color-bg-primary, #ffffff)',
    tooltipColor: 'var(--color-text-primary, #111827)',
}
