import type { ComponentType } from 'react'

import { isErrorSource, isFeedbackSource, sourceInfo, toSourceProduct } from '@/model/sources'
import type { InboxItem, SourceProduct } from '@/model/types'
import { BrainIcon } from '@/ui/icons/BrainIcon'
import { CalendarIcon } from '@/ui/icons/CalendarIcon'
import { ClockIcon } from '@/ui/icons/ClockIcon'
import { RefreshIcon } from '@/ui/icons/RefreshIcon'
import { SparklesIcon } from '@/ui/icons/SparklesIcon'
import type { IconProps } from '@/ui/icons/types'

export type InboxSort = 'recommended' | 'last_updated' | 'newest' | 'oldest' | 'model_score'
export type CreatedWindow = 'any' | '24h' | '3d' | '7d' | '14d'
export type SourceFilterKey =
    | 'error'
    | 'github'
    | 'gitlab'
    | 'pganalyze'
    | 'analytics'
    | 'session_replay'
    | 'llm_analytics'
    | 'logs'
    | 'health_checks'
    | 'report'
    | 'endpoints'
    | 'support'
    | 'linear'
    | 'jira'
    | 'engineering_analytics'
    | 'dashboard'

export interface InboxFilters {
    sort: InboxSort
    createdWindow: CreatedWindow
    /** Empty means every source. */
    sources: readonly SourceFilterKey[]
}

export const DEFAULT_INBOX_FILTERS: InboxFilters = { sort: 'recommended', createdWindow: 'any', sources: [] }

export interface SortOption {
    key: InboxSort
    label: string
    description?: string
    Icon: ComponentType<IconProps>
}

export const SORT_OPTIONS: readonly SortOption[] = [
    { key: 'recommended', label: 'Recommended', Icon: SparklesIcon },
    { key: 'last_updated', label: 'Last updated', Icon: RefreshIcon },
    { key: 'newest', label: 'Newest', Icon: CalendarIcon },
    { key: 'oldest', label: 'Oldest', Icon: ClockIcon },
]

export const MODEL_SCORE_SORT_OPTION: SortOption = {
    key: 'model_score',
    label: 'Model score',
    description: 'Only for team 2',
    Icon: BrainIcon,
}

export interface CreatedWindowOption {
    key: CreatedWindow
    label: string
    /** Segment text; five segments share one row at phone width. */
    shortLabel: string
    hours: number | null
}

export const CREATED_WINDOW_OPTIONS: readonly CreatedWindowOption[] = [
    { key: 'any', label: 'Any time', shortLabel: 'Any', hours: null },
    { key: '24h', label: 'Last 24 hours', shortLabel: '24h', hours: 24 },
    { key: '3d', label: 'Last 3 days', shortLabel: '3d', hours: 72 },
    { key: '7d', label: 'Last 7 days', shortLabel: '7d', hours: 168 },
    { key: '14d', label: 'Last 14 days', shortLabel: '14d', hours: 336 },
]

export interface SourceFilterOption {
    key: SourceFilterKey
    label: string
    Icon: ComponentType<IconProps>
}

// The source product whose label and icon each option shows, in the order the options appear.
const OPTION_SOURCE: Record<SourceFilterKey, SourceProduct> = {
    error: 'error_tracking',
    github: 'github',
    gitlab: 'gitlab',
    pganalyze: 'pganalyze',
    analytics: 'analytics',
    session_replay: 'session_replay',
    llm_analytics: 'llm_analytics',
    logs: 'logs',
    health_checks: 'health_checks',
    report: 'other',
    endpoints: 'endpoints',
    support: 'conversations',
    linear: 'linear',
    jira: 'jira',
    engineering_analytics: 'engineering_analytics',
    dashboard: 'dashboard',
}

export const SOURCE_FILTER_OPTIONS: readonly SourceFilterOption[] = (
    Object.entries(OPTION_SOURCE) as [SourceFilterKey, SourceProduct][]
).map(([key, source]) => ({ key, ...sourceInfo(source) }))

const FILTER_KEY_BY_PRODUCT: Record<SourceProduct, SourceFilterKey> = {
    error_tracking: 'error',
    sentry: 'error',
    github: 'github',
    gitlab: 'gitlab',
    pganalyze: 'pganalyze',
    analytics: 'analytics',
    session_replay: 'session_replay',
    replay_vision: 'session_replay',
    llm_analytics: 'llm_analytics',
    logs: 'logs',
    health_checks: 'health_checks',
    signals_scout: 'report',
    signals_check: 'report',
    other: 'report',
    endpoints: 'endpoints',
    conversations: 'support',
    zendesk: 'support',
    intercom: 'support',
    linear: 'linear',
    jira: 'jira',
    engineering_analytics: 'engineering_analytics',
    dashboard: 'dashboard',
}

/** Raw source product (the backend `source_product` value) to the mobile group it filters under. */
export function sourceFilterKeyFor(sourceProduct: string): SourceFilterKey {
    // The predicates know error and feedback products that `toSourceProduct` folds into `other`.
    if (isErrorSource(sourceProduct)) {
        return 'error'
    }
    if (isFeedbackSource(sourceProduct)) {
        return 'support'
    }
    return FILTER_KEY_BY_PRODUCT[toSourceProduct(sourceProduct)]
}

function filterKeysOf(item: InboxItem): SourceFilterKey[] {
    return item.sources.length > 0 ? item.sources.map(sourceFilterKeyFor) : ['report']
}

/** The options that match at least one item, plus every selected key, in SOURCE_FILTER_OPTIONS order. */
export function sourceFilterOptionsFor(
    items: readonly InboxItem[],
    selected: readonly SourceFilterKey[]
): SourceFilterOption[] {
    const shown = new Set<SourceFilterKey>(selected)
    for (const item of items) {
        for (const key of filterKeysOf(item)) shown.add(key)
    }
    return SOURCE_FILTER_OPTIONS.filter((option) => shown.has(option.key))
}

function timeOf(iso: string): number {
    const time = Date.parse(iso)
    return Number.isNaN(time) ? Number.NEGATIVE_INFINITY : time
}

type Compare = (a: InboxItem, b: InboxItem) => number

const COMPARE: Record<Exclude<InboxSort, 'recommended'>, Compare> = {
    last_updated: (a, b) => timeOf(b.updatedAt) - timeOf(a.updatedAt),
    newest: (a, b) => timeOf(b.createdAt) - timeOf(a.createdAt),
    oldest: (a, b) => timeOf(a.createdAt) - timeOf(b.createdAt),
    model_score: (a, b) => {
        if (a.modelScore === null || b.modelScore === null) {
            return (a.modelScore === null ? 1 : 0) - (b.modelScore === null ? 1 : 0)
        }
        return b.modelScore - a.modelScore
    },
}

/** Filter, then sort. `recommended` keeps the input order. Sorts are stable. `model_score` is descending with null last. */
export function applyInboxFilters(items: readonly InboxItem[], filters: InboxFilters, now: number): InboxItem[] {
    const hours = CREATED_WINDOW_OPTIONS.find((option) => option.key === filters.createdWindow)?.hours ?? null
    const since = hours === null ? null : now - hours * 3_600_000
    const selected = new Set(filters.sources)
    const kept = items.filter(
        (item) =>
            (since === null || timeOf(item.createdAt) >= since) &&
            (selected.size === 0 || filterKeysOf(item).some((key) => selected.has(key)))
    )
    if (filters.sort === 'recommended') {
        return kept
    }
    const compare = COMPARE[filters.sort]
    // The index tiebreak keeps equal items in ranking order on any engine.
    return kept
        .map((item, index) => ({ item, index }))
        .sort((a, b) => compare(a.item, b.item) || a.index - b.index)
        .map(({ item }) => item)
}

export function isDefaultInboxFilters(filters: InboxFilters): boolean {
    return (
        filters.sort === DEFAULT_INBOX_FILTERS.sort &&
        filters.createdWindow === DEFAULT_INBOX_FILTERS.createdWindow &&
        filters.sources.length === 0
    )
}
