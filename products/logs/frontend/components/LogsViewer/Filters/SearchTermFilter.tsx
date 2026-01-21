import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { logsSceneLogic } from '../../../logsSceneLogic'

export const SearchTermFilter = (): JSX.Element => {
    const { searchTerm } = useValues(logsSceneLogic)
    const { setSearchTerm } = useActions(logsSceneLogic)

    return (
        <LemonInput
            size="small"
            value={searchTerm}
            onChange={(value) => setSearchTerm(value)}
            placeholder="Search logs..."
        />
    )
}
