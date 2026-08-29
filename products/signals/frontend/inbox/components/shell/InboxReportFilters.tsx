import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import {
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    inboxPriorityFilterLabel,
    inboxSortOptionKey,
    PRIORITY_ACCENT,
    PRIORITY_MEANING,
} from '../../filterOptions'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { SignalReportPriority } from '../../types'

const ALL_PRIORITIES = null

const PRIORITY_SELECT_OPTIONS = [
    { value: ALL_PRIORITIES, label: 'All priorities' },
    ...INBOX_PRIORITY_OPTIONS.map((priority) => ({
        value: priority,
        label: `${priority} · ${PRIORITY_MEANING[priority].label}`,
        icon: (
            <span
                className="size-2 rounded-full"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: PRIORITY_ACCENT[priority] }}
            />
        ),
    })),
]

// No icons: the trigger reads out the active option, and an icon there would crowd the label the
// order is already stated in.
const SORT_SELECT_OPTIONS = INBOX_SORT_OPTIONS.map((option) => ({
    value: inboxSortOptionKey(option.field, option.direction),
    label: option.label,
}))

/**
 * What narrows the report list: priority, then sort order. There is no status filter, because the
 * sections below are the status split. Filter state is persisted via `inboxFiltersLogic`, and every
 * section reloads on change.
 *
 * Reviewer scope is deliberately not here. It sits with triage mode on the other side of the row,
 * because it picks whose inbox this is rather than narrowing the one you are looking at.
 */
export function InboxReportFilters(): JSX.Element {
    const { sortField, sortDirection, priorityFilter } = useValues(inboxFiltersLogic)
    const { setSort, setPriorityFilter } = useActions(inboxFiltersLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                size="small"
                value={priorityFilter.length === 1 ? priorityFilter[0] : ALL_PRIORITIES}
                onChange={(priority) => setPriorityFilter(priority ? [priority as SignalReportPriority] : [])}
                options={PRIORITY_SELECT_OPTIONS}
                // A shared link can carry several priorities, which no single option represents.
                // Read the selection out of the filter itself so the button never understates it.
                renderButtonContent={() => inboxPriorityFilterLabel(priorityFilter)}
                data-attr="inbox-filter-priority"
            />
            <LemonSelect
                size="small"
                value={inboxSortOptionKey(sortField, sortDirection)}
                onChange={(key) => {
                    const option = INBOX_SORT_OPTIONS.find((o) => inboxSortOptionKey(o.field, o.direction) === key)
                    if (option) {
                        setSort(option.field, option.direction)
                    }
                }}
                options={SORT_SELECT_OPTIONS}
                renderButtonContent={(leaf) => `Sort: ${leaf?.label ?? ''}`}
                data-attr="inbox-sort"
            />
        </div>
    )
}
