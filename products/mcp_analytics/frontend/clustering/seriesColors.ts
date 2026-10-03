import type { ChartTheme } from '@posthog/quill-charts'

/**
 * Indices into the shared series palette, so the clustering tab draws data in the same
 * colours as the dashboard and tool quality charts. Those tabs index the theme directly;
 * naming the two the clustering views need keeps the choice in one place.
 */
export const PRIMARY_SERIES = 0
export const ERROR_SERIES = 4

export function seriesColor(theme: ChartTheme, index: number): string {
    // The palette is short and wraps in the chart helpers; mirror that rather than
    // returning undefined and letting a fill fall back to black.
    return theme.colors[index % theme.colors.length]
}
