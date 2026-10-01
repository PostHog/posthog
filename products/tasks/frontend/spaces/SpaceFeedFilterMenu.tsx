import { useActions, useValues } from 'kea'

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { TodayFilterMenuTrigger } from '~/layout/today/TodayFilterMenuTrigger'
import { RECENT_CREATED_BY_OPTIONS } from '~/layout/today/todayRecentFilters'
import { DEFAULT_RECENT_SORT, RECENT_SORT_OPTIONS } from '~/layout/today/todayRecentOrder'
import { TodayRecentRadioSubmenu } from '~/layout/today/TodayRecentRadioSubmenu'
import { TodayRecentSourceSubmenu } from '~/layout/today/TodayRecentSourceSubmenu'

import {
    DEFAULT_SPACE_FEED_FILTERS,
    SpaceFeedEnvironmentFilter,
    SpaceFeedGrouping,
    SpaceFeedPinnedFilter,
    SpaceFeedStatusFilter,
} from './spaceFeedEntries'
import { spaceFeedViewLogic } from './spaceFeedViewLogic'

const GROUPING_OPTIONS: { value: SpaceFeedGrouping; label: string }[] = [
    { value: 'date', label: 'Date' },
    { value: 'repository', label: 'Repository' },
]

const STATUS_OPTIONS: { value: SpaceFeedStatusFilter; label: string }[] = [
    { value: 'any', label: 'Any status' },
    { value: 'unread', label: 'Unread' },
]

const PINNED_OPTIONS: { value: SpaceFeedPinnedFilter; label: string }[] = [
    { value: 'any', label: 'All sessions' },
    { value: 'pinned', label: 'Pinned only' },
]

const ENVIRONMENT_OPTIONS: { value: SpaceFeedEnvironmentFilter; label: string }[] = [
    { value: 'any', label: 'Anywhere' },
    { value: 'local', label: 'Local' },
    { value: 'cloud', label: 'Cloud' },
]

/** The space feed's sort, grouping and filters behind the funnel button, like PostHog Desktop's. */
export function SpaceFeedFilterMenu({ sourceOptions }: { sourceOptions: string[] }): JSX.Element {
    const { filters, filtersActive, sort, grouping } = useValues(spaceFeedViewLogic)
    const { setFilters, clearFilters, setSort, setGrouping } = useActions(spaceFeedViewLogic)

    return (
        <DropdownMenu>
            <TodayFilterMenuTrigger active={filtersActive} dataAttr="today-space-feed-filter" />
            <DropdownMenuContent align="end" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Group by"
                    options={GROUPING_OPTIONS}
                    value={grouping}
                    defaultValue="date"
                    onChange={setGrouping}
                    dataAttr="today-space-feed-group-by"
                />
                <TodayRecentRadioSubmenu
                    label="Sort by"
                    options={RECENT_SORT_OPTIONS}
                    value={sort}
                    defaultValue={DEFAULT_RECENT_SORT}
                    onChange={setSort}
                    dataAttr="today-space-feed-sort-by"
                />
                <DropdownMenuSeparator />
                <TodayRecentRadioSubmenu
                    label="Status"
                    options={STATUS_OPTIONS}
                    value={filters.status}
                    defaultValue={DEFAULT_SPACE_FEED_FILTERS.status}
                    onChange={(status) => setFilters({ ...filters, status })}
                    dataAttr="today-space-feed-filter-status"
                />
                <TodayRecentRadioSubmenu
                    label="Created by"
                    options={RECENT_CREATED_BY_OPTIONS}
                    value={filters.createdBy}
                    defaultValue={DEFAULT_SPACE_FEED_FILTERS.createdBy}
                    onChange={(createdBy) => setFilters({ ...filters, createdBy })}
                    dataAttr="today-space-feed-filter-created-by"
                />
                <TodayRecentRadioSubmenu
                    label="Pinned"
                    options={PINNED_OPTIONS}
                    value={filters.pinned}
                    defaultValue={DEFAULT_SPACE_FEED_FILTERS.pinned}
                    onChange={(pinned) => setFilters({ ...filters, pinned })}
                    dataAttr="today-space-feed-filter-pinned"
                />
                <TodayRecentRadioSubmenu
                    label="Environment"
                    options={ENVIRONMENT_OPTIONS}
                    value={filters.environment}
                    defaultValue={DEFAULT_SPACE_FEED_FILTERS.environment}
                    onChange={(environment) => setFilters({ ...filters, environment })}
                    dataAttr="today-space-feed-filter-environment"
                />
                <TodayRecentSourceSubmenu
                    selected={filters.sources}
                    options={sourceOptions}
                    onChange={(sources) => setFilters({ ...filters, sources })}
                    dataAttr="today-space-feed-filter-source"
                />
                {filtersActive && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={clearFilters}
                            data-attr="today-space-feed-filter-clear"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
