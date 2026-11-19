// PROTOTYPE (throwaway): the calendar's filters and how they narrow the entries.
import { CalendarEntry, Channel, EntryKind } from './prototypeData'

export type StatusFilter = 'any' | 'scheduled' | 'sent' | 'problem'

export interface CalendarFilters {
    search: string
    kinds: EntryKind[]
    channels: Channel[]
    status: StatusFilter
    /** Off: a repeating workflow shows once, in the Repeating row, instead of on every day it runs. */
    showRepeats: boolean
}

export const DEFAULT_FILTERS: CalendarFilters = {
    search: '',
    kinds: [],
    channels: [],
    status: 'any',
    showRepeats: false,
}

export function filtersOn(filters: CalendarFilters): boolean {
    return filters.kinds.length > 0 || filters.channels.length > 0 || filters.status !== 'any'
}

export function matches(entry: CalendarEntry, filters: CalendarFilters): boolean {
    if (filters.kinds.length && !filters.kinds.includes(entry.kind)) {
        return false
    }
    if (filters.channels.length && !filters.channels.includes(entry.channel)) {
        return false
    }
    if (filters.status === 'scheduled' && entry.state !== 'scheduled') {
        return false
    }
    if (filters.status === 'sent' && entry.state !== 'sent') {
        return false
    }
    if (filters.status === 'problem' && entry.state !== 'failed' && entry.state !== 'paused') {
        return false
    }
    if (filters.search && !entry.name.toLowerCase().includes(filters.search.toLowerCase())) {
        return false
    }
    return true
}

export function showsVolume(filters: CalendarFilters): boolean {
    return (
        (filters.kinds.length === 0 || filters.kinds.includes('transactional')) &&
        (filters.channels.length === 0 || filters.channels.includes('email')) &&
        filters.status !== 'scheduled' &&
        !filters.search
    )
}
