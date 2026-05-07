/** BubbleUp UI copy — heatmap brush vs baseline attribute enrichment */

export const BUBBLE_UP_BUTTON_TOOLTIP =
    'Runs BubbleUp on your brush: finds span and resource attributes that show up more often in that time and duration slice than in the rest of your filtered chart period. Use it to spot routes, versions, or dimensions tied to what you selected.'

export const BUBBLE_UP_MODAL_TOOLTIP =
    'BubbleUp compares OTLP span and resource attributes inside your heatmap selection to a baseline: the same filters over your chart date range. Lift above 1 means that key/value pair accounts for a larger share of attribute occurrences in the slice than overall — helpful for hypotheses, not proof of cause.'

export const BUBBLE_UP_COLUMN_TOOLTIPS = {
    key: 'OpenTelemetry attribute name.',
    value: 'Attribute value on spans in the rollup.',
    type: 'Whether the attribute came from the span or the resource.',
    lift: 'Ratio of how common this key/value is inside your selection versus the baseline. Values above 1 are enriched in the brush; near 1 matches normal traffic.',
    inset: 'How many times this attribute pair appeared on spans in your brushed region.',
    baseline: 'How many times this pair appeared in the baseline rollup over your chart date range.',
} as const
