import { useActions, useValues } from 'kea'

import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { AssigneeSelect } from './AssigneeSelect'

export function AssigneeFilter(): JSX.Element {
    const { assignee } = useValues(issueQueryOptionsLogic)
    const { setAssignee } = useActions(issueQueryOptionsLogic)

    return <AssigneeSelect assignee={assignee ?? null} onChange={setAssignee} />
}
