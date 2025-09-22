import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AssigneeLabelDisplay } from '../Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../Assignee/AssigneeSelect'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'

export const AssigneeFilter = (): JSX.Element => {
    const { assignee } = useValues(issueQueryOptionsLogic)
    const { setAssignee } = useActions(issueQueryOptionsLogic)

    return (
        <AssigneeSelect assignee={assignee ?? null} onChange={(assignee) => setAssignee(assignee)}>
            {(displayAssignee) => (
                <LemonButton type="secondary" size="small">
                    <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Any assignee" />
                </LemonButton>
            )}
        </AssigneeSelect>
    )
}
