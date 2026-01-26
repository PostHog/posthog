import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'

import { logsSceneLogic } from '../../../logsSceneLogic'

export const SearchTermFilter = (): JSX.Element => {
    const { searchTerm } = useValues(logsSceneLogic)
    const { setSearchTerm } = useActions(logsSceneLogic)
    const { setFilter } = useActions(logsViewerConfigLogic)

    return (
        <LemonInput
            size="small"
            value={searchTerm}
            onChange={(value) => {
                setSearchTerm(value)
                setFilter('searchTerm', value)
            }}
            placeholder="Search logs..."
        />
    )
}
