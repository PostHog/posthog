import { useActions, useValues } from 'kea'

import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { ErrorTrackingStatusSelect } from './ErrorTrackingStatusSelect'

export const StatusFilter = (): JSX.Element => {
    const { status } = useValues(issueQueryOptionsLogic)
    const { setStatus } = useActions(issueQueryOptionsLogic)

    return (
        <ErrorTrackingStatusSelect
            value={status ?? 'active'}
            onChange={(value) => setStatus(value === 'all' ? 'all' : value)}
        />
    )
}
