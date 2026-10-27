import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { adPerformanceMetricKey } from '../adPerformanceMetrics'

export type OverviewMetricGroup = 'platforms' | 'posthog'

export interface OverviewMetricGroupConfiguration {
    hidden: string[]
    order: string[]
    collapsed: boolean
}

export type OverviewMetricConfiguration = Record<OverviewMetricGroup, OverviewMetricGroupConfiguration>

export const OVERVIEW_METRIC_GROUPS: { key: OverviewMetricGroup; label: string; description: string }[] = [
    { key: 'platforms', label: 'Ad platforms', description: 'Metrics reported by your connected ad platforms' },
    { key: 'posthog', label: 'PostHog', description: 'Your conversion goals and cost per result' },
]

export function defaultOverviewMetricConfiguration(): OverviewMetricConfiguration {
    return {
        platforms: { hidden: [], order: [], collapsed: false },
        posthog: { hidden: [], order: [], collapsed: false },
    }
}

export type OverviewHiddenGroups = 'none' | OverviewMetricGroup | 'both'

export function hiddenOverviewMetricGroups(configuration: OverviewMetricConfiguration): OverviewHiddenGroups {
    const platforms = configuration.platforms.hidden.length > 0
    const posthog = configuration.posthog.hidden.length > 0
    if (platforms && posthog) {
        return 'both'
    }
    return platforms ? 'platforms' : posthog ? 'posthog' : 'none'
}

export function overviewMetricsForGroup(
    items: OverviewMetricCardItem[],
    group: OverviewMetricGroup,
    configuration: OverviewMetricConfiguration
): OverviewMetricCardItem[] {
    const metrics = items.filter((item) => !!adPerformanceMetricKey(item.key) === (group === 'platforms'))
    const byKey = new Map(metrics.map((item) => [item.key, item]))
    const keys = [...new Set([...configuration[group].order, ...metrics.map((item) => item.key)])]
    return keys.flatMap((key) => {
        const item = byKey.get(key)
        return item ? [item] : []
    })
}
