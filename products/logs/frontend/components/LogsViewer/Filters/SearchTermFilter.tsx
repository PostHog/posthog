import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

export const SearchTermFilter = (): JSX.Element => {
    const { filters } = useValues(logsViewerFiltersLogic)
    const { searchTerm } = filters
    const { setSearchTerm } = useActions(logsViewerFiltersLogic)

    return (
        <LemonInput
            size="small"
            value={searchTerm}
            onChange={(value) => {
                setSearchTerm(value)
            }}
            placeholder="Search logs..."
        />
    )
}
