import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronDown, IconFlag, IconRefresh, IconSearch, IconSort, IconTarget } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import {
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    INBOX_SOURCE_OPTIONS,
    PRIORITY_ACCENT,
    PRIORITY_MEANING,
    inboxPriorityFilterLabel,
    inboxSortOptionKey,
    inboxSourceFilterLabel,
} from '../../filterOptions'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { scoutFleetLogic } from '../../logics/scoutFleetLogic'
import { prettifyScoutSkillName } from '../../utils/scoutRunsWindow'
import { FilterItem, FilterPopover } from './filterControls'

/**
 * Collapsible per-scout sub-filter nested under the "Scout" source row. Collapsed by default
 * (fleets can be large); auto-expanded while any scout is selected so active filters stay visible.
 */
function ScoutSubFilter({
    scoutNames,
    scoutFilter,
    onToggle,
    onClear,
}: {
    scoutNames: string[]
    scoutFilter: string[]
    onToggle: (scout: string) => void
    onClear: () => void
}): JSX.Element {
    const [expanded, setExpanded] = useState(scoutFilter.length > 0)
    // Auto-expand whenever a scout selection appears — including URL navigation or persisted-state
    // hydration into an already-mounted popover — so active filters stay visible. Still collapsible
    // by hand once no scout is selected.
    useEffect(() => {
        if (scoutFilter.length > 0) {
            setExpanded(true)
        }
    }, [scoutFilter.length])
    return (
        <div className="pl-5">
            <div className="flex items-center justify-between gap-1">
                <button
                    type="button"
                    onClick={() => setExpanded(!expanded)}
                    className="flex min-w-0 flex-1 items-center gap-1 rounded px-1.5 py-1 text-left text-xs text-muted transition-colors hover:bg-surface-secondary"
                >
                    <IconChevronDown
                        className={`shrink-0 text-sm transition-transform ${expanded ? '' : '-rotate-90'}`}
                    />
                    <span>
                        Filter by scout
                        {scoutFilter.length > 0 && <span className="text-default"> · {scoutFilter.length}</span>}
                    </span>
                </button>
                {scoutFilter.length > 0 && (
                    <LemonButton size="xsmall" type="tertiary" onClick={onClear}>
                        Clear
                    </LemonButton>
                )}
            </div>
            {expanded && (
                <div className="max-h-48 overflow-y-auto deprecated-space-y-px">
                    {scoutNames.map((skillName) => (
                        <FilterItem
                            key={skillName}
                            label={prettifyScoutSkillName(skillName)}
                            active={scoutFilter.includes(skillName)}
                            onClick={() => onToggle(skillName)}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

interface InboxSearchFilterBarProps {
    searchPlaceholder?: string
    /** Triggers a reload of the report list (lives on `inboxSceneLogic`). */
    onRefresh?: () => void
    refreshing?: boolean
}

/**
 * Search input + Sort / Source / Priority filter popovers + refresh. There is no
 * status filter (desktop dropped it; status is a fixed request constant). Each
 * popover stays a quiet, muted chip until its filter is in use, then gains a
 * solid border and shows its value. Filter state is persisted via
 * `inboxFiltersLogic`; the central scene reloads on change.
 */
export function InboxSearchFilterBar({
    searchPlaceholder = 'Search by title or description…',
    onRefresh,
    refreshing,
}: InboxSearchFilterBarProps): JSX.Element {
    const { searchQuery, sortField, sortDirection, sourceProductFilter, scoutFilter, priorityFilter } =
        useValues(inboxFiltersLogic)
    const { setSearchQuery, setSort, toggleSourceProduct, toggleScout, clearScoutFilter, togglePriority } =
        useActions(inboxFiltersLogic)
    const { scoutConfigs } = useValues(scoutFleetLogic)

    const activeSort = INBOX_SORT_OPTIONS.find((o) => o.field === sortField && o.direction === sortDirection)
    const activeSortKey = inboxSortOptionKey(sortField, sortDirection)

    // Selected scouts always stay listed (even if their config was since deleted) so they can be untoggled.
    const scoutNames = [...new Set([...(scoutConfigs ?? []).map((c) => c.skill_name), ...scoutFilter])].sort((a, b) =>
        prettifyScoutSkillName(a).localeCompare(prettifyScoutSkillName(b))
    )

    return (
        <div className="flex items-center gap-2 flex-wrap w-full">
            <LemonInput
                className="min-w-[220px] max-w-[420px] [&_.LemonInput__input]:pr-4"
                type="search"
                value={searchQuery}
                onChange={setSearchQuery}
                placeholder={searchPlaceholder}
                prefix={<IconSearch />}
                size="small"
            />

            {/* ml-auto right-aligns the cluster; flex-wrap + max-w-full keep the controls from
                overflowing on narrow viewports — each can wrap within the group rather than the
                whole row clipping, the behavior the flat (ungrouped) layout had before. */}
            <div className="flex flex-wrap items-center justify-end gap-2 ml-auto max-w-full">
                <FilterPopover
                    label="Sort"
                    value={activeSort?.label ?? 'Priority first'}
                    icon={<IconSort />}
                    active={activeSortKey !== 'priority:asc'}
                >
                    {INBOX_SORT_OPTIONS.map((option) => (
                        <FilterItem
                            key={inboxSortOptionKey(option.field, option.direction)}
                            icon={option.icon}
                            label={option.label}
                            active={sortField === option.field && sortDirection === option.direction}
                            onClick={() => setSort(option.field, option.direction)}
                        />
                    ))}
                </FilterPopover>

                <FilterPopover
                    label="Source"
                    value={inboxSourceFilterLabel(sourceProductFilter, scoutFilter)}
                    icon={<IconTarget />}
                    active={sourceProductFilter.length > 0 || scoutFilter.length > 0}
                >
                    {INBOX_SOURCE_OPTIONS.map((option) => (
                        <div key={option.value}>
                            <FilterItem
                                icon={option.icon}
                                label={option.label}
                                active={sourceProductFilter.includes(option.value)}
                                onClick={() => toggleSourceProduct(option.value)}
                            />
                            {option.value === 'signals_scout' && scoutNames.length > 0 && (
                                <ScoutSubFilter
                                    scoutNames={scoutNames}
                                    scoutFilter={scoutFilter}
                                    onToggle={toggleScout}
                                    onClear={clearScoutFilter}
                                />
                            )}
                        </div>
                    ))}
                </FilterPopover>

                <FilterPopover
                    label="Priority"
                    value={inboxPriorityFilterLabel(priorityFilter)}
                    icon={<IconFlag />}
                    active={priorityFilter.length > 0}
                >
                    {INBOX_PRIORITY_OPTIONS.map((priority) => (
                        <FilterItem
                            key={priority}
                            icon={
                                <span
                                    className="size-2 rounded-full"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ backgroundColor: PRIORITY_ACCENT[priority] }}
                                />
                            }
                            label={
                                <span>
                                    {priority}
                                    <span className="text-muted"> · {PRIORITY_MEANING[priority].label}</span>
                                </span>
                            }
                            active={priorityFilter.includes(priority)}
                            onClick={() => togglePriority(priority)}
                        />
                    ))}
                </FilterPopover>

                {onRefresh && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        icon={<IconRefresh />}
                        loading={refreshing}
                        tooltip="Refresh"
                        aria-label="Refresh"
                        onClick={onRefresh}
                        className="bg-surface-primary"
                    />
                )}
            </div>
        </div>
    )
}
