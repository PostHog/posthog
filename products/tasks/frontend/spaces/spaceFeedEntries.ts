import { Dayjs, dayjs } from 'lib/dayjs'

import { DEFAULT_RECENT_FILTERS, TodayRecentFilters, filterRecentItems } from '~/layout/today/todayRecentFilters'
import {
    TodayRecentGrouping,
    TodayRecentSort,
    groupRecentItems,
    sortRecentItems,
} from '~/layout/today/todayRecentOrder'
import { TodayWorkItem } from '~/layout/today/todayWorkItems'

import { TaskPullRequest, spacePullRequests } from './taskPullRequests'

export type SpaceFeedType = 'task' | 'pr'

/** The feed's type toggles, in the order they show. */
export const SPACE_FEED_TYPES: { value: SpaceFeedType; label: string }[] = [
    { value: 'task', label: 'Tasks' },
    { value: 'pr', label: 'PRs' },
]

export const DEFAULT_SPACE_FEED_TYPES: SpaceFeedType[] = SPACE_FEED_TYPES.map((type) => type.value)

export type SpaceFeedStatusFilter = 'any' | 'unread'
export type SpaceFeedPinnedFilter = 'any' | 'pinned'
export type SpaceFeedEnvironmentFilter = 'any' | 'local' | 'cloud'
/** A space holds one space's sessions, so the feed does not group by space. */
export type SpaceFeedGrouping = Exclude<TodayRecentGrouping, 'space'>

export interface SpaceFeedFilters extends TodayRecentFilters {
    status: SpaceFeedStatusFilter
    pinned: SpaceFeedPinnedFilter
    environment: SpaceFeedEnvironmentFilter
}

export const DEFAULT_SPACE_FEED_FILTERS: SpaceFeedFilters = {
    ...DEFAULT_RECENT_FILTERS,
    status: 'any',
    pinned: 'any',
    environment: 'any',
}

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
    return filterRecentItems(items, '', filters, { userId, unreadIds, pinnedIds }).filter(
        (item) =>
            (filters.status === 'any' || unreadIds.has(item.id)) &&
            (filters.pinned === 'any' || pinnedIds.has(item.id)) &&
            (filters.environment === 'any' || item.runEnvironment === filters.environment)
    )
}

export type SpaceFeedEntry =
    | { kind: 'task'; key: string; item: TodayWorkItem }
    | { kind: 'pr'; key: string; item: TodayWorkItem; pullRequest: TaskPullRequest }

export interface SpaceFeedSection {
    key: string
    /** Null for a run with nothing to call it, like an alphabetical list. */
    label: string | null
    entries: SpaceFeedEntry[]
}

/** The shown types' entries, sorted and cut into sections the way the Recent list is. */
export function spaceFeedSections(
    items: TodayWorkItem[],
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
    ]
    const byKey = new Map(entries.map((entry) => [entry.key, entry]))
    // A PR sorts and groups by its session, so each entry goes through the Recent helpers as that session under its own key.
    const keyed = entries.map((entry) => ({ ...entry.item, id: entry.key }))
    return groupRecentItems(sortRecentItems(keyed, sort), sort, grouping, {}, now).map((section) => ({
        key: section.key,
        label: section.label,
        entries: section.items.flatMap((item) => byKey.get(item.id) ?? []),
    }))
}
