import { type ChartTheme } from '@posthog/quill-charts'

// PostHog brand palette. Canvas can't read CSS custom properties, so we hand the
// chart concrete hexes. The chart picks one per series by index; legends use the
// same array to stay in sync.
export const CHART_COLORS = [
    '#1d4aff', // PostHog blue
    '#621da6', // PostHog purple
    '#00d683', // PostHog green
    '#f54e00', // PostHog orange
    '#f7a501', // PostHog yellow
    '#dc2626', // red
]

// Picks a palette color by index, wrapping when there are more series than colors.
export const colorAt = (index: number): string => CHART_COLORS[index % CHART_COLORS.length]!

// Single mid-gray for axis labels — readable on both light and dark hosts. Claude
// Desktop's iframe doesn't set `prefers-color-scheme`, so we can't detect the host
// theme and adapt at runtime.
export const CHART_THEME: ChartTheme = {
    colors: CHART_COLORS,
    backgroundColor: '#ffffff',
    axisColor: '#9ca3af',
    gridColor: 'rgba(128, 128, 128, 0.2)',
    crosshairColor: 'rgba(128, 128, 128, 0.5)',
    tooltipBackground: '#ffffff',
    tooltipColor: '#111827',
}
