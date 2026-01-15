import { useActions, useValues } from 'kea'

import { IconClock, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuSection } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter } from 'lib/utils'

import { AnyPropertyFilter } from '~/types'

import { logsLogic } from '../logsLogic'
import { LogsFiltersHistoryEntry } from '../types'

const formatDateRange = (dateRange: LogsFiltersHistoryEntry['filters']['dateRange']): string => {
    const from = dateRange.date_from || 'any'
    const to = dateRange.date_to || 'now'
    return `${from} → ${to}`
}

const isPropertyFilter = (v: unknown): v is AnyPropertyFilter => {
    return typeof v === 'object' && v !== null && 'key' in v
}

const formatFilterGroupValues = (filterGroup: LogsFiltersHistoryEntry['filters']['filterGroup']): string[] => {
    const group = filterGroup?.values?.[0]
    if (!group || !('values' in group)) {
        return []
    }

    return group.values.filter(isPropertyFilter).map((filter) => {
        const key = filter.key || '?'
        const value = Array.isArray(filter.value) ? filter.value.join(', ') : String(filter.value ?? '')
        const truncatedValue = value.length > 15 ? `${value.slice(0, 15)}...` : value
        return `${key}=${truncatedValue}`
    })
}

const formatHistoryEntryDetails = (entry: LogsFiltersHistoryEntry): string => {
    const parts: string[] = []
    const { filters } = entry

    parts.push(formatDateRange(filters.dateRange))

    if (filters.severityLevels && filters.severityLevels.length > 0) {
        parts.push(filters.severityLevels.map((l) => capitalizeFirstLetter(l)).join(', '))
    }

    if (filters.searchTerm) {
        const truncated = filters.searchTerm.length > 20 ? `${filters.searchTerm.slice(0, 20)}...` : filters.searchTerm
        parts.push(`"${truncated}"`)
    }

    const attributeFilters = formatFilterGroupValues(filters.filterGroup)
    if (attributeFilters.length > 0) {
        parts.push(attributeFilters.join(', '))
    }

    return parts.join(' | ')
}

const formatServiceNames = (entry: LogsFiltersHistoryEntry): string => {
    const { filters } = entry
    const serviceNames = filters.serviceNames

    if (serviceNames && serviceNames.length > 0) {
        const maxDisplayed = 3
        const displayedNames = serviceNames.slice(0, maxDisplayed)
        const remainingCount = serviceNames.length - displayedNames.length
        const baseText = displayedNames.join(', ')

        if (remainingCount > 0) {
            return `${baseText} and ${remainingCount} more`
        }

        return baseText
    }
    return 'All services'
}

const formatRelativeTime = (timestamp: number): string => {
    return dayjs(timestamp).fromNow()
}

const HistoryEntryButton = ({
    entry,
    onClick,
}: {
    entry: LogsFiltersHistoryEntry
    onClick: () => void
}): JSX.Element => {
    return (
        <button
            type="button"
            onClick={onClick}
            className="flex flex-col gap-0.5 w-full text-left px-2 py-1.5 rounded cursor-pointer hover:bg-fill-highlight-100 transition-colors"
        >
            <span className="text-xs text-muted font-medium">{formatServiceNames(entry)}</span>
            <span className="text-sm">{formatHistoryEntryDetails(entry)}</span>
            <span className="text-xs text-muted">{formatRelativeTime(entry.timestamp)}</span>
        </button>
    )
}

export const FilterHistoryDropdown = (): JSX.Element | null => {
    const { filterHistory, hasFilterHistory } = useValues(logsLogic)
    const { restoreFiltersFromHistory, clearFilterHistory } = useActions(logsLogic)

    if (!hasFilterHistory) {
        return null
    }

    const sections: LemonMenuSection[] = [
        {
            title: 'Recent filters',
            items: filterHistory.map((entry, index) => ({
                label: () => <HistoryEntryButton entry={entry} onClick={() => restoreFiltersFromHistory(index)} />,
            })),
        },
        {
            items: [
                {
                    label: 'Clear history',
                    icon: <IconTrash />,
                    onClick: () => clearFilterHistory(),
                    status: 'danger' as const,
                },
            ],
        },
    ]

    return (
        <LemonMenu items={sections}>
            <LemonButton icon={<IconClock />} size="small" type="secondary" tooltip="Filter history" />
        </LemonMenu>
    )
}
