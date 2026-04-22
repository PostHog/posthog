import { useActions, useValues } from 'kea'

import { IconClock, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuSection } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { getFiltersSummaryLines } from 'products/logs/frontend/utils'

import { LogsFiltersHistoryEntry } from '../../../types'
import { logsFilterHistoryLogic } from './logsFilterHistoryLogic'

const formatHistoryEntryDetails = (entry: LogsFiltersHistoryEntry): string => {
    return getFiltersSummaryLines(entry.filters)
        .filter((line) => line.label !== 'Service' && line.label !== 'Services')
        .map((line) => line.value)
        .join(' | ')
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
    const { filterHistory, hasFilterHistory } = useValues(logsFilterHistoryLogic)
    const { restoreFiltersFromHistory, clearFilterHistory } = useActions(logsFilterHistoryLogic)

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
