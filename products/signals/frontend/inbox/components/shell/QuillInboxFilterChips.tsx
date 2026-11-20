import { useActions } from 'kea'

import { Button, Chip, ChipClose } from '@posthog/quill'

import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { useInboxFilterChips } from './useInboxFilterChips'

export function QuillInboxFilterChips(): JSX.Element | null {
    const chips = useInboxFilterChips()
    const { clearFilters } = useActions(inboxFiltersLogic)

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
            <Button size="sm" variant="link-muted" onClick={() => clearFilters()} data-attr="inbox-filter-chips-clear">
                Clear filters
            </Button>
        </div>
    )
}
