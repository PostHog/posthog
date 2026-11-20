import { useActions, useValues } from 'kea'

import { Chip, ChipClose } from '@posthog/quill'

import { INBOX_CREATED_WINDOW_OPTIONS, inboxPriorityFilterLabel, inboxSourceFilterLabel } from '../../filterOptions'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'

export function QuillInboxFilterChips(): JSX.Element | null {
    const { priorityFilter, activeSourceProductFilter, activeScoutFilter, activeCreatedWindow } =
        useValues(inboxFiltersLogic)
    const { setPriorityFilter, setSourceFilter, setCreatedWindow } = useActions(inboxFiltersLogic)
    const window = INBOX_CREATED_WINDOW_OPTIONS.find((option) => option.value === activeCreatedWindow)
    const chips = [
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

    if (chips.length === 0) {
        return null
    }
    return (
        <div className="-mb-2 flex flex-wrap items-center gap-1.5" data-attr="inbox-filter-chips">
            {chips.map((chip) => (
                <Chip key={chip.key}>
                    {chip.label}
                    <ChipClose
                        aria-label={`Remove the filter ${chip.label}`}
                        onClick={chip.onRemove}
                        data-attr={`inbox-filter-chip-remove-${chip.key}`}
                    />
                </Chip>
            ))}
        </div>
    )
}
