import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { adPerformanceMetricKey } from '../adPerformanceMetrics'

export type OverviewMetricSource = 'platforms' | 'posthog'

export const MAX_OVERVIEW_METRICS = 5

const DEFAULT_POSTHOG_METRICS = 2

export const OVERVIEW_METRIC_SOURCES: { key: OverviewMetricSource; label: string }[] = [
    { key: 'platforms', label: 'Ad platforms' },
    { key: 'posthog', label: 'PostHog' },
]

export function overviewMetricSource(key: string): OverviewMetricSource {
    return adPerformanceMetricKey(key) ? 'platforms' : 'posthog'
}

export function defaultOverviewMetricSelection(items: OverviewMetricCardItem[]): string[] {
    const platforms = items.filter((item) => overviewMetricSource(item.key) === 'platforms').map((item) => item.key)
    const posthog = items
        .filter((item) => overviewMetricSource(item.key) === 'posthog')
        .slice(0, DEFAULT_POSTHOG_METRICS)
        .map((item) => item.key)
    return [...platforms.slice(0, MAX_OVERVIEW_METRICS - posthog.length), ...posthog]
}

export function shownOverviewMetrics(
    items: OverviewMetricCardItem[],
    selection: string[] | null
): OverviewMetricCardItem[] {
    const byKey = new Map(items.map((item) => [item.key, item]))
    const saved = (selection ?? []).flatMap((key) => byKey.get(key) ?? [])
    if (saved.length > 0) {
        return saved.slice(0, MAX_OVERVIEW_METRICS)
    }
    return defaultOverviewMetricSelection(items).flatMap((key) => byKey.get(key) ?? [])
}

export function toggleOverviewMetric(selection: string[], key: string): string[] {
    if (selection.includes(key)) {
        return selection.filter((selected) => selected !== key)
    }
    return selection.length < MAX_OVERVIEW_METRICS ? [...selection, key] : selection
}

export function moveOverviewMetric(selection: string[], key: string, direction: -1 | 1): string[] {
    const index = selection.indexOf(key)
    const target = index + direction
    if (index < 0 || target < 0 || target >= selection.length) {
        return selection
    }
    const next = [...selection]
    ;[next[index], next[target]] = [next[target], next[index]]
    return next
}

export type OverviewHiddenSources = 'none' | OverviewMetricSource | 'both'

export function hiddenOverviewMetricSources(selection: string[]): OverviewHiddenSources {
    const shown = new Set(selection.map(overviewMetricSource))
    const platforms = !shown.has('platforms')
    const posthog = !shown.has('posthog')
    if (platforms && posthog) {
        return 'both'
    }
    return platforms ? 'platforms' : posthog ? 'posthog' : 'none'
}
