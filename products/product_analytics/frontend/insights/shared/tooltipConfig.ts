import type { TooltipConfig } from '@posthog/quill-charts'

/** Shared config for the unified insight tooltip. */
export const INSIGHT_TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'cursor' }

/** Dashboard tiles sit side by side, so an embedded chart keeps its tooltip inside the chart. */
export const EMBEDDED_INSIGHT_TOOLTIP_CONFIG: TooltipConfig = { ...INSIGHT_TOOLTIP_CONFIG, boundary: 'chart' }
