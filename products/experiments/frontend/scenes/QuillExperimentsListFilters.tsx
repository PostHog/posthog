import { useActions, useValues } from 'kea'
import { type ReactNode } from 'react'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuSeparator,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
    FilterSearchSubMenu,
} from '@posthog/quill'

import { QuillTagsFilterSubMenu } from 'lib/components/QuillTagsFilterSubMenu'
import { fullName } from 'lib/utils/strings'
import { AnalyticsOwnerAvatar } from 'scenes/analytics/AnalyticsOwner'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { userLogic } from 'scenes/userLogic'

import { membersLogic } from '~/models/membersLogic'
import { ExperimentStatus } from '~/types'

import { QuillExperimentVelocityStats } from 'products/experiments/frontend/components/QuillExperimentVelocityStats'
import { experimentsLogic } from 'products/experiments/frontend/scenes/experimentsLogic'

const DEFAULT_ORDER = '-created_at'

const ORDER_LABELS: Record<string, string> = {
    created_at: 'Created',
    start_date: 'Started',
    end_date: 'Ended',
    updated_at: 'Updated',
    duration: 'Duration',
    status: 'Status',
    conclusion: 'Result',
    created_by: 'Owner',
    name: 'Name',
}

const SORT_OPTIONS: FilterOption[] = [
    { value: '-created_at', label: 'Created' },
    { value: '-start_date', label: 'Started' },
    { value: '-duration', label: 'Duration' },
    { value: 'status', label: 'Status' },
    { value: 'conclusion', label: 'Result' },
]

const STATUS_OPTIONS: FilterOption<'all' | ExperimentStatus>[] = [
    { value: 'all', label: 'All' },
    { value: ExperimentStatus.Draft, label: 'Draft' },
    { value: ExperimentStatus.Running, label: 'Running' },
    { value: ExperimentStatus.Paused, label: 'Paused' },
    { value: ExperimentStatus.ExposureFrozen, label: 'Exposure frozen' },
    { value: ExperimentStatus.Stopped, label: 'Complete' },
]

const SHOW_OPTIONS: FilterOption<'active' | 'archived'>[] = [
    { value: 'active', label: 'Active' },
    { value: 'archived', label: 'Archived' },
]

/** A header click can set an order the menu doesn't list, so it shows as a row only while it is in force. */
function sortOptionsFor(order: string): FilterOption[] {
    if (SORT_OPTIONS.some((option) => option.value === order)) {
        return SORT_OPTIONS
    }
    const key = order.replace(/^-/, '')
    const label = ORDER_LABELS[key] ?? key
    return [...SORT_OPTIONS, { value: order, label: `${label}, ${order.startsWith('-') ? 'descending' : 'ascending'}` }]
}

function QuillExperimentsFilterMenu(): JSX.Element {
    const { filters } = useValues(experimentsLogic)
    const { setExperimentsFilters } = useActions(experimentsLogic)
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)

    const order = filters.order ?? DEFAULT_ORDER
    const createdBy = (filters.created_by_id ?? []).map(String)
    const narrowingFiltersActive =
        (!!filters.status && filters.status !== 'all') ||
        createdBy.length > 0 ||
        (filters.tags?.length ?? 0) > 0 ||
        (filters.excluded_tags?.length ?? 0) > 0 ||
        !!filters.archived

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                // The Created by row names the people picked, so it needs them as soon as the menu shows.
                if (open && createdBy.length > 0) {
                    ensureAllMembersLoaded()
                }
            }}
        >
            <FilterMenuTrigger active={narrowingFiltersActive} dataAttr="experiments-list-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterRadioSubMenu
                    label="Sort by"
                    options={sortOptionsFor(order)}
                    value={order}
                    onChange={(next) => setExperimentsFilters({ order: next, page: 1 })}
                    optionDataAttr="experiments-list-sort"
                />
                <DropdownMenuSeparator />
                <FilterRadioSubMenu
                    label="Status"
                    options={STATUS_OPTIONS}
                    value={filters.status ?? 'all'}
                    defaultValue="all"
                    onChange={(status) => {
                        if (status === 'all') {
                            const { status: _, ...rest } = filters
                            setExperimentsFilters({ ...rest, page: 1 }, true)
                        } else {
                            setExperimentsFilters({ status, page: 1 })
                        }
                    }}
                    dataAttr="experiments-list-status"
                    optionDataAttr="experiments-list-status-option"
                />
                <FilterSearchSubMenu
                    label="Created by"
                    allLabel="Any user"
                    pluralNoun="people"
                    options={meFirstMembers.map((member) => ({
                        value: String(member.user.id),
                        label: fullName(member.user) || member.user.email,
                        icon: <AnalyticsOwnerAvatar owner={member.user} />,
                        hint: member.user.uuid === user?.uuid ? '(you)' : undefined,
                    }))}
                    selected={createdBy}
                    onChange={(ids) => {
                        if (ids.length === 0) {
                            const { created_by_id: _, ...rest } = filters
                            setExperimentsFilters({ ...rest, page: 1 }, true)
                        } else {
                            setExperimentsFilters({ created_by_id: ids.map(Number), page: 1 })
                        }
                    }}
                    loading={membersLoading}
                    searchPlaceholder="Search people"
                    emptyText="No one matches"
                    onOpen={ensureAllMembersLoaded}
                    dataAttr="experiments-list-created-by"
                    optionDataAttr="experiments-list-created-by-option"
                />
                <QuillTagsFilterSubMenu
                    logicKey="experiments-list-tags"
                    selected={filters.tags ?? []}
                    onChange={(tags) => setExperimentsFilters({ tags: tags.length > 0 ? tags : undefined, page: 1 })}
                    dataAttr="experiment-select-tags"
                    optionDataAttr="experiments-list-tags-option"
                />
                <QuillTagsFilterSubMenu
                    label="Exclude tags"
                    allLabel="No tags"
                    logicKey="experiments-list-excluded-tags"
                    selected={filters.excluded_tags ?? []}
                    onChange={(excludedTags) =>
                        setExperimentsFilters({
                            excluded_tags: excludedTags.length > 0 ? excludedTags : undefined,
                            page: 1,
                        })
                    }
                    dataAttr="experiment-select-excluded-tags"
                    optionDataAttr="experiments-list-excluded-tags-option"
                />
                <FilterRadioSubMenu
                    label="Show"
                    options={SHOW_OPTIONS}
                    value={filters.archived ? 'archived' : 'active'}
                    defaultValue="active"
                    onChange={(show) => setExperimentsFilters({ archived: show === 'archived', page: 1 })}
                    dataAttr="experiments-list-archived"
                    optionDataAttr="experiments-list-archived-option"
                />
                <DropdownMenuSeparator />
                <FilterClearItem
                    active={narrowingFiltersActive}
                    onClear={() =>
                        setExperimentsFilters(
                            {
                                ...(filters.search ? { search: filters.search } : {}),
                                ...(filters.order ? { order: filters.order } : {}),
                                archived: false,
                                page: 1,
                            },
                            true
                        )
                    }
                    dataAttr="experiments-list-clear"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/** Search, the one menu of the list's controls, then whatever the list adds, like the analytics list. */
export function QuillExperimentsListFilters({ children }: { children?: ReactNode }): JSX.Element {
    const { filters } = useValues(experimentsLogic)
    const { setExperimentsFilters } = useActions(experimentsLogic)

    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <AnalyticsSearchInput
                    value={filters.search || ''}
                    onChange={(search) => setExperimentsFilters({ search, page: 1 })}
                    label="Search experiments"
                    placeholder="Search by name or flag"
                    dataAttr="experiments-list-search"
                />
                <QuillExperimentsFilterMenu />
                {children}
            </div>
            <QuillExperimentVelocityStats />
        </div>
    )
}
