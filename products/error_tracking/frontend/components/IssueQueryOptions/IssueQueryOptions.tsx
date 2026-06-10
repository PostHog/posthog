import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { issuesDataNodeLogic } from '../../logics/issuesDataNodeLogic'

export const IssueReloadButton = (): JSX.Element => {
    const { responseLoading } = useValues(issuesDataNodeLogic)
    const { reloadData, cancelQuery } = useActions(issuesDataNodeLogic)

    return (
        <LemonButton
            type="tertiary"
            size="small"
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    reloadData()
                }
            }}
            icon={responseLoading ? <Spinner textColored /> : <IconRefresh />}
            tooltip={responseLoading ? 'Cancel' : 'Reload'}
        />
    )
}
