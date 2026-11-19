// PROTOTYPE (throwaway): the calendar's one filter menu, laid out like the analytics list's.
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuSeparator,
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
    FilterRadioSubMenu,
} from '@posthog/quill'

import { CalendarFilters, DEFAULT_FILTERS, StatusFilter, filtersOn } from './calendarFilters'
import { Channel, EntryKind } from './prototypeData'

export function CalendarFilterMenu({
    filters,
    onChange,
}: {
    filters: CalendarFilters
    onChange: (filters: CalendarFilters) => void
}): JSX.Element {
    return (
        <DropdownMenu>
            <FilterMenuTrigger active={filtersOn(filters)} dataAttr="calendar-prototype-filter" />
            <DropdownMenuContent align="end" className="min-w-64">
                <FilterCheckboxSubMenu<EntryKind>
                    label="Type"
                    allLabel="All types"
                    pluralNoun="types"
                    options={[
                        { value: 'broadcast', label: 'Broadcasts' },
                        { value: 'workflow', label: 'Workflows' },
                        { value: 'transactional', label: 'Transactional' },
                    ]}
                    selected={filters.kinds}
                    onChange={(kinds) => onChange({ ...filters, kinds })}
                />
                <FilterRadioSubMenu<StatusFilter>
                    label="Status"
                    options={[
                        { value: 'any', label: 'Any status' },
                        { value: 'scheduled', label: 'Scheduled' },
                        { value: 'sent', label: 'Sent' },
                        { value: 'problem', label: 'Failed or paused' },
                    ]}
                    value={filters.status}
                    defaultValue="any"
                    onChange={(status) => onChange({ ...filters, status })}
                />
                <FilterCheckboxSubMenu<Channel>
                    label="Channel"
                    allLabel="All channels"
                    pluralNoun="channels"
                    options={[
                        { value: 'email', label: 'Email' },
                        { value: 'sms', label: 'SMS' },
                        { value: 'push', label: 'Push' },
                    ]}
                    selected={filters.channels}
                    onChange={(channels) => onChange({ ...filters, channels })}
                />
                <DropdownMenuSeparator />
                <DropdownMenuCheckboxItem
                    checked={filters.showRepeats}
                    closeOnClick={false}
                    onCheckedChange={(checked) => onChange({ ...filters, showRepeats: checked })}
                >
                    Show each run of a repeating workflow
                </DropdownMenuCheckboxItem>
                <FilterClearItem
                    active={filtersOn(filters)}
                    onClear={() =>
                        onChange({ ...DEFAULT_FILTERS, search: filters.search, showRepeats: filters.showRepeats })
                    }
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
