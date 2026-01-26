import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'

export const SearchTermFilter = (): JSX.Element => {
    const {
        filters: { searchTerm },
    } = useValues(logsViewerConfigLogic)
    const { setFilter } = useActions(logsViewerConfigLogic)

    return (
        <LemonInput
            size="small"
            value={searchTerm}
            onChange={(value) => {
                setFilter('searchTerm', value)
            }}
            placeholder="Search logs..."
        />
    )
}
