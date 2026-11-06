import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import {
    INBOX_PRIORITY_OPTIONS,
    inboxPriorityFilterLabel,
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

/** Narrows the report list to one priority. Each option leads with a dot in the priority badge's color. */
export function InboxPriorityFilter(): JSX.Element {
    const { priorityFilter } = useValues(inboxFiltersLogic)
    const { setPriorityFilter } = useActions(inboxFiltersLogic)

    return (
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
    )
}
