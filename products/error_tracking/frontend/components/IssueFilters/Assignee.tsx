import { useActions, useValues } from 'kea'

import { ErrorTrackingAssigneeSelectButton } from '../Assignee/ErrorTrackingAssigneeSelectButton'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'

export const AssigneeFilter = (): JSX.Element => {
    const { assignee } = useValues(issueQueryOptionsLogic)
    const { setAssignee } = useActions(issueQueryOptionsLogic)

    return <ErrorTrackingAssigneeSelectButton assignee={assignee ?? null} onChange={(value) => setAssignee(value)} />
}
