import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { ScoutEnabledFilter, ScoutRosterSort, scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutTagsFilter } from './ScoutTagsFilter'

const ENABLED_FILTER_OPTIONS: { value: ScoutEnabledFilter; label: string }[] = [
    { value: 'all', label: 'All scouts' },
    { value: 'enabled', label: 'Turned on' },
    { value: 'disabled', label: 'Turned off' },
]

const SORT_OPTIONS: { value: ScoutRosterSort; label: string }[] = [
    { value: 'name', label: 'Name' },
    { value: 'status', label: 'Status' },
]

/**
 * What narrows the roster, in the same shape as the report toolbar: search first, then the on/off
 * filter, the tag filter, and the sort order as dropdown buttons. Filter state lives in
 * `scoutFleetLogic`, which also fires the filter analytics.
 */
export function ScoutsRosterFilters(): JSX.Element {
    const { scoutSearch, scoutEnabledFilter, scoutRosterSort, scoutTagOptions, activeScoutTags } =
        useValues(scoutFleetLogic)
    const { setScoutSearch, setScoutEnabledFilter, setScoutRosterSort, setScoutTagFilter } = useActions(scoutFleetLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonInput
                type="search"
                size="small"
                placeholder="Search scouts…"
                value={scoutSearch}
                onChange={setScoutSearch}
                className="w-48"
                allowClear
                data-attr="inbox-scout-search"
            />
            <LemonSelect
                size="small"
                value={scoutEnabledFilter}
                onChange={(filter) => filter && setScoutEnabledFilter(filter)}
                options={ENABLED_FILTER_OPTIONS}
                data-attr="inbox-scout-filter-enabled"
            />
            {scoutTagOptions.length > 0 && (
                <ScoutTagsFilter
                    options={scoutTagOptions}
                    selected={activeScoutTags}
                    onToggle={(tag) =>
                        setScoutTagFilter(
                            activeScoutTags.includes(tag)
                                ? activeScoutTags.filter((candidate) => candidate !== tag)
                                : [...activeScoutTags, tag]
                        )
                    }
                    onClear={() => setScoutTagFilter([])}
                />
            )}
            <LemonSelect
                size="small"
                value={scoutRosterSort}
                onChange={(sort) => sort && setScoutRosterSort(sort)}
                options={SORT_OPTIONS}
                renderButtonContent={(leaf) => `Sort: ${leaf?.label ?? ''}`}
                data-attr="inbox-scout-sort"
            />
        </div>
    )
}
