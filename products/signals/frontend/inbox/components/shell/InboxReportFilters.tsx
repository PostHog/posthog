import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import {
    INBOX_CREATED_WINDOW_OPTIONS,
    INBOX_PRIORITY_OPTIONS,
    inboxPriorityFilterLabel,
    PRIORITY_ACCENT,
    PRIORITY_MEANING,
} from '../../filterOptions'
import { InboxCreatedWindow, inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { SignalReportPriority } from '../../types'
import { InboxSourceFilter } from './InboxSourceFilter'
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

const ANY_TIME = null
const CREATED_WINDOW_SELECT_OPTIONS: { value: InboxCreatedWindow | null; label: string }[] = [
    { value: ANY_TIME, label: 'Any time' },
    ...INBOX_CREATED_WINDOW_OPTIONS.map(({ value, label }) => ({ value, label })),
]

function createdWindowLabel(window: InboxCreatedWindow | null): string {
    return CREATED_WINDOW_SELECT_OPTIONS.find((option) => option.value === window)?.label ?? 'Any time'
}

/**
 * What narrows the report list: report state, then priority, then the created-in window, then source.
 * Filter state is persisted via `inboxFiltersLogic`, and the list reloads on change.
 *
 * Source goes last because its label grows with the selected scout name. Anywhere earlier, a long name
 * pushes the controls after it to the right.
 *
 * Sort and reviewer scope are deliberately not here. Sort orders the list rather than narrowing it,
 * and scope picks whose inbox this is, so both sit after a divider at the end of the row.
 */
export function InboxReportFilters(): JSX.Element {
    const { priorityFilter, timeWindowAvailable, createdWindow, sourceFilterAvailable } = useValues(inboxFiltersLogic)
    const { setPriorityFilter, setCreatedWindow } = useActions(inboxFiltersLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InboxStateFilter />
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
            {timeWindowAvailable && (
                <LemonSelect
                    size="small"
                    value={createdWindow}
                    onChange={(window) => setCreatedWindow(window)}
                    options={CREATED_WINDOW_SELECT_OPTIONS}
                    icon={<IconCalendar />}
                    tooltip={`Created: ${createdWindowLabel(createdWindow)}`}
                    // The window value ("7d") doubles as the short label in a narrow container.
                    renderButtonContent={(leaf) => (
                        <>
                            <span className="@2xl:hidden">{leaf?.value ?? 'Any time'}</span>
                            <span className="hidden @2xl:inline">{leaf?.label ?? 'Any time'}</span>
                        </>
                    )}
                    data-attr="inbox-filter-created-window"
                />
            )}
            {sourceFilterAvailable && <InboxSourceFilter />}
        </div>
    )
}
