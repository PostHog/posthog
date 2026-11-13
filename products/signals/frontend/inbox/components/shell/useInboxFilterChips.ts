import { useActions, useValues } from 'kea'

import { INBOX_CREATED_WINDOW_OPTIONS, inboxPriorityFilterLabel, inboxSourceFilterLabel } from '../../filterOptions'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'

export interface InboxFilterChip {
    key: string
    label: string
    onRemove: () => void
}

/** The filters in force that narrow the list, one entry each. The Filter button counts them and the chip row shows them. */
export function useInboxFilterChips(): InboxFilterChip[] {
    const { priorityFilter, activeSourceProductFilter, activeScoutFilter, activeCreatedWindow } =
        useValues(inboxFiltersLogic)
    const { setPriorityFilter, setSourceFilter, setCreatedWindow } = useActions(inboxFiltersLogic)
    const window = INBOX_CREATED_WINDOW_OPTIONS.find((option) => option.value === activeCreatedWindow)
    return [
        priorityFilter.length > 0 && {
            key: 'priority',
            label: inboxPriorityFilterLabel(priorityFilter),
            onRemove: () => setPriorityFilter([]),
        },
        activeSourceProductFilter.length + activeScoutFilter.length > 0 && {
            key: 'source',
            label: inboxSourceFilterLabel(activeSourceProductFilter, activeScoutFilter),
            onRemove: () => setSourceFilter(null),
        },
        window && { key: 'created', label: window.label, onRemove: () => setCreatedWindow(null) },
    ].filter((chip) => !!chip)
}
