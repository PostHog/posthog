export { useToolResult, type UseToolResultOptions, type UseToolResultReturn } from './useToolResult'

// Re-export capture for direct usage in components
export { capture } from '../analytics/posthog'

// Re-export types for convenience
export type { AnalyticsMetadata, WithAnalytics, ExtractData } from '../types'
export { hasAnalytics, extractAnalytics } from '../types'
