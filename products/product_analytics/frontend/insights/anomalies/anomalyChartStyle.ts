// The row charts of the Anomalies tab and their legend share these, so each legend swatch looks like what it names.
export const ANOMALY_FILL_COLOR_VAR = 'danger'
export const ANOMALY_FILL_OPACITY = 0.2
// Anomalous buckets before the selected range did not put the series in the list, so they draw fainter.
export const EARLIER_ANOMALY_FILL_OPACITY = 0.08
export const ANOMALY_POINT_RADIUS = 3

// A dot on top of the faint shading needs more color than the shading to stay visible.
export function earlierAnomalyPointColor(fillColor: string): string {
    return `color-mix(in srgb, ${fillColor} 40%, transparent)`
}
export const RANGE_START_LINE_BORDER = '1px dashed var(--color-graph-axis-label)'
