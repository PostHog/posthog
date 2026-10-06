import { Dayjs, dayjs } from 'lib/dayjs'

import {
    TodayRecentGrouping,
    TodayRecentSort,
    groupRecentItems,
    sortRecentItems,
} from '~/layout/today/todayRecentOrder'
import { TodayWorkItem } from '~/layout/today/todayWorkItems'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { TaskPullRequest, spacePullRequests } from './taskPullRequests'

export type SpaceFeedType = 'task' | 'canvas' | 'pr'

/** The feed's type toggles, in the order they show. */
export const SPACE_FEED_TYPES: { value: SpaceFeedType; label: string }[] = [
    { value: 'task', label: 'Tasks' },
    { value: 'canvas', label: 'Canvases' },
    { value: 'pr', label: 'PRs' },
]

export const DEFAULT_SPACE_FEED_TYPES: SpaceFeedType[] = SPACE_FEED_TYPES.map((type) => type.value)

export type SpaceFeedView = 'list' | 'cards'

export type SpaceFeedStatusFilter = 'any' | 'unread'
export type SpaceFeedPinnedFilter = 'any' | 'pinned'
export type SpaceFeedEnvironmentFilter = 'any' | 'local' | 'cloud'
export type SpaceFeedCreatedByFilter = 'anyone' | 'me' | 'others'
export type SpaceFeedGrouping = TodayRecentGrouping

export interface SpaceFeedFilters {
    status: SpaceFeedStatusFilter
    createdBy: SpaceFeedCreatedByFilter
    pinned: SpaceFeedPinnedFilter
    environment: SpaceFeedEnvironmentFilter
    sources: string[]
}

export const DEFAULT_SPACE_FEED_FILTERS: SpaceFeedFilters = {
    status: 'any',
    createdBy: 'anyone',
    pinned: 'any',
    environment: 'any',
    sources: [],
}

export const SPACE_FEED_CREATED_BY_OPTIONS: { value: SpaceFeedCreatedByFilter; label: string }[] = [
    { value: 'anyone', label: 'Anyone' },
    { value: 'me', label: 'Me' },
    { value: 'others', label: 'Other people' },
]

export function hasActiveSpaceFeedFilters(filters: SpaceFeedFilters): boolean {
    return (
        filters.createdBy !== DEFAULT_SPACE_FEED_FILTERS.createdBy ||
        filters.status !== DEFAULT_SPACE_FEED_FILTERS.status ||
        filters.pinned !== DEFAULT_SPACE_FEED_FILTERS.pinned ||
        filters.environment !== DEFAULT_SPACE_FEED_FILTERS.environment ||
        filters.sources.length > 0
    )
}

export interface SpaceFeedFilterContext {
    userId: number | null
    unreadIds: Set<string>
    pinnedIds: Set<string>
}

export function filterSpaceFeedItems(
    items: TodayWorkItem[],
    filters: SpaceFeedFilters,
    { userId, unreadIds, pinnedIds }: SpaceFeedFilterContext
): TodayWorkItem[] {
    return items.filter(
        (item) =>
            (filters.status === 'any' || unreadIds.has(item.id)) &&
            (filters.pinned === 'any' || pinnedIds.has(item.id)) &&
            (filters.environment === 'any' || item.runEnvironment === filters.environment) &&
            (filters.createdBy === 'anyone' ||
                (item.createdById !== null && (filters.createdBy === 'me') === (item.createdById === userId))) &&
            (!filters.sources.length || (item.source !== null && filters.sources.includes(item.source)))
    )
}

export function filterSpaceFeedCanvases(
    canvases: CanvasApi[],
    filters: SpaceFeedFilters,
    userId: number | null
): CanvasApi[] {
    // A canvas has no unread state, pin, run or source, so a filter on any of those leaves no canvas.
    if (
        filters.status !== 'any' ||
        filters.pinned !== 'any' ||
        filters.environment !== 'any' ||
        filters.sources.length > 0
    ) {
        return []
    }
    return canvases.filter((canvas) => {
        const mine = canvas.created_by.id === userId
        return filters.createdBy === 'anyone' || (filters.createdBy === 'me' ? mine : !mine)
    })
}

export type SpaceFeedEntry =
    | { kind: 'task'; key: string; item: TodayWorkItem }
    | { kind: 'pr'; key: string; item: TodayWorkItem; pullRequest: TaskPullRequest }
    | { kind: 'canvas'; key: string; canvas: CanvasApi }

export interface SpaceFeedSection {
    key: string
    /** Null for a run with nothing to call it, like an alphabetical list. */
    label: string | null
    entries: SpaceFeedEntry[]
}

/** A canvas in the shape the Recent helpers sort and group by: its name, its dates and its space. */
function canvasOrderItem(canvas: CanvasApi, key: string): TodayWorkItem {
    return {
        kind: 'session',
        id: key,
        title: canvas.name,
        timestamp: canvas.updated_at,
        createdAt: canvas.created_at,
        status: null,
        channel: canvas.channel,
        createdById: canvas.created_by.id,
        author: null,
        latestRunId: null,
        runEnvironment: null,
        originProduct: null,
        source: null,
        repository: null,
        branch: null,
        pullRequests: [],
        finalMessage: null,
    }
}

/** The shown types' entries, sorted and cut into sections the way the Recent list is. */
export function spaceFeedSections(
    items: TodayWorkItem[],
    canvases: CanvasApi[],
    types: SpaceFeedType[],
    sort: TodayRecentSort,
    grouping: SpaceFeedGrouping,
    now: Dayjs = dayjs()
): SpaceFeedSection[] {
    const entries: SpaceFeedEntry[] = [
        ...(types.includes('task') ? items.map((item) => ({ kind: 'task' as const, key: item.id, item })) : []),
        ...(types.includes('pr')
            ? spacePullRequests(items).map(({ pullRequest, session }) => ({
                  kind: 'pr' as const,
                  key: `pr:${pullRequest.url}`,
                  item: session,
                  pullRequest,
              }))
            : []),
        ...(types.includes('canvas')
            ? canvases.map((canvas) => ({ kind: 'canvas' as const, key: `canvas:${canvas.id}`, canvas }))
            : []),
    ]
    const byKey = new Map(entries.map((entry) => [entry.key, entry]))
    // A PR sorts and groups by its session, so each entry goes through the Recent helpers as that session under its own key.
    const keyed = entries.map((entry) =>
        entry.kind === 'canvas' ? canvasOrderItem(entry.canvas, entry.key) : { ...entry.item, id: entry.key }
    )
    return groupRecentItems(sortRecentItems(keyed, sort), sort, grouping, now).map((section) => ({
        key: section.key,
        label: section.label,
        entries: section.items.flatMap((item) => byKey.get(item.id) ?? []),
    }))
}
