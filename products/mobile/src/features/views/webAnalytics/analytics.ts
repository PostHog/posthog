import { track } from '@/lib/analytics'
import type { WebBreakdown, WebTileId, WebTrendMetric } from '@/model/views'

// Filter events name the property, never the value: a path or a campaign name can carry customer data.

export type WebAnalyticsSurface = 'card' | 'list'
export type WebFilterRemovedSource = 'chip' | 'clear_all' | 'undo' | 'row'
export type WebTileLink = 'goals' | 'web_vitals' | 'error_tracking' | 'session_replay' | 'frustrating_pages'

export function trackWebMetricSelected(props: { metric: WebTrendMetric }): void {
    track('mobile_web_analytics_metric_selected', { metric: props.metric })
}

export function trackWebBreakdownChanged(props: {
    tile: WebTileId
    breakdown: WebBreakdown
    from: WebAnalyticsSurface
}): void {
    track('mobile_web_analytics_breakdown_changed', { tile: props.tile, breakdown: props.breakdown, from: props.from })
}

export function trackWebFilterAdded(props: { property: string; source: WebAnalyticsSurface | 'undo' }): void {
    track('mobile_web_analytics_filter_added', { property: props.property, source: props.source })
}

export function trackWebFilterRemoved(props: { property: string; source: WebFilterRemovedSource }): void {
    track('mobile_web_analytics_filter_removed', { property: props.property, source: props.source })
}

export function trackWebListOpened(props: { tile: WebTileId; breakdown: WebBreakdown }): void {
    track('mobile_web_analytics_list_opened', { tile: props.tile, breakdown: props.breakdown })
}

export function trackWebTileOpened(props: { tile: WebTileLink }): void {
    track('mobile_web_analytics_web_tile_opened', { tile: props.tile })
}
