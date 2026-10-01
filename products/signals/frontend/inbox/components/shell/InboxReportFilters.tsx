import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import {
    INBOX_CREATED_WINDOW_OPTIONS,
    INBOX_MODEL_SORT_OPTIONS,
    INBOX_PRIORITY_OPTIONS,
    INBOX_SORT_OPTIONS,
    inboxPriorityFilterLabel,
    inboxSortOptionKey,
    PRIORITY_ACCENT,
    InboxSortOption,
    PRIORITY_MEANING,
} from '../../filterOptions'
import { InboxCreatedWindow, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { SignalReportPriority } from '../../types'
import { InboxStateFilter } from './InboxStateFilter'

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
const toSortSelectOption = (option: InboxSortOption): { value: string; label: string } => ({
    value: inboxSortOptionKey(option.field, option.direction),
    label: option.label,
})
const SORT_SELECT_OPTIONS = INBOX_SORT_OPTIONS.map(toSortSelectOption)
const SORT_SELECT_SECTIONS_WITH_MODEL = [
    { options: SORT_SELECT_OPTIONS },
    { title: 'Model', options: INBOX_MODEL_SORT_OPTIONS.map(toSortSelectOption) },
]
const ALL_SORT_OPTIONS = [...INBOX_SORT_OPTIONS, ...INBOX_MODEL_SORT_OPTIONS]

const ANY_TIME = null
const CREATED_WINDOW_SELECT_OPTIONS: { value: InboxCreatedWindow | null; label: string }[] = [
    { value: ANY_TIME, label: 'Any time' },
    ...INBOX_CREATED_WINDOW_OPTIONS.map(({ value, label }) => ({ value, label })),
]

/**
 * What narrows the report list: priority, then report state, then sort order, then the created-in window. Filter state is
 * persisted via `inboxFiltersLogic`, and the list reloads on change.
 *
 * Reviewer scope is deliberately not here. It sits with triage mode on the other side of the row,
 * because it picks whose inbox this is rather than narrowing the one you are looking at.
 */
export function InboxReportFilters(): JSX.Element {
    const {
        activeSortField,
        activeSortDirection,
        priorityFilter,
        modelSortAvailable,
        timeWindowAvailable,
        createdWindow,
    } = useValues(inboxFiltersLogic)
    const { setSort, setPriorityFilter, setCreatedWindow } = useActions(inboxFiltersLogic)
    const sortOptions = modelSortAvailable ? ALL_SORT_OPTIONS : INBOX_SORT_OPTIONS

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
            <InboxStateFilter />
            <LemonSelect
                size="small"
                value={inboxSortOptionKey(activeSortField, activeSortDirection)}
                onChange={(key) => {
                    const option = sortOptions.find((o) => inboxSortOptionKey(o.field, o.direction) === key)
                    if (option) {
                        setSort(option.field, option.direction)
                    }
                }}
                options={modelSortAvailable ? SORT_SELECT_SECTIONS_WITH_MODEL : SORT_SELECT_OPTIONS}
                renderButtonContent={(leaf) => `Sort: ${leaf?.label ?? ''}`}
                data-attr="inbox-sort"
            />
            {timeWindowAvailable && (
                <LemonSelect
                    size="small"
                    value={createdWindow}
                    onChange={(window) => setCreatedWindow(window)}
                    options={CREATED_WINDOW_SELECT_OPTIONS}
                    renderButtonContent={(leaf) => `Created: ${leaf?.label ?? 'Any time'}`}
                    data-attr="inbox-filter-created-window"
                />
            )}
        </div>
    )
}
