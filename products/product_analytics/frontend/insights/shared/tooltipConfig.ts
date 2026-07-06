import type { TooltipConfig } from '@posthog/quill-charts'

/** Tooltip config for the new unified tooltip (product-analytics-insights-tooltips flag on). */
export const INSIGHT_TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'cursor' }

/** Legacy tooltip config used when the flag is off. */
export const INSIGHT_TOOLTIP_CONFIG_LEGACY: TooltipConfig = { pinnable: true, placement: 'top' }
