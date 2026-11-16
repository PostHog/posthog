import { track } from '@/lib/analytics'
import type { CreatedWindow, InboxFilters, InboxSort, SourceFilterKey } from './filters'
import { useInboxFiltersStore } from './inboxFiltersStore'

export function inboxFilterActions(filters: InboxFilters): {
    setSort: (sort: InboxSort) => void
    setCreatedWindow: (window: CreatedWindow) => void
    toggleSource: (source: SourceFilterKey) => void
    clearFilters: () => void
} {
    const setSort = (sort: InboxSort): void => {
        if (sort === filters.sort) {
            return
        }
        track('mobile_inbox_sort_changed', { sort })
        useInboxFiltersStore.getState().setSort(sort)
    }
    const setCreatedWindow = (window: CreatedWindow): void => {
        if (window === filters.createdWindow) {
            return
        }
        track('mobile_inbox_created_window_changed', { window })
        useInboxFiltersStore.getState().setCreatedWindow(window)
    }
    const toggleSource = (source: SourceFilterKey): void => {
        const selected = !filters.sources.includes(source)
        track('mobile_inbox_source_filter_changed', {
            source,
            selected,
            count: filters.sources.length + (selected ? 1 : -1),
        })
        useInboxFiltersStore.getState().toggleSource(source)
    }
    const clearFilters = (): void => {
        track('mobile_inbox_filters_cleared')
        useInboxFiltersStore.getState().clear()
    }

    return { setSort, setCreatedWindow, toggleSource, clearFilters }
}
