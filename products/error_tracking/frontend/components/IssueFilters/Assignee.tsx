import { useActions, useValues } from 'kea'

import { Button, SelectTriggerIcon } from 'lib/ui/quill'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from '../Assignee/AssigneeDisplay'
import { QuillAssigneeSelect } from '../Assignee/QuillAssigneeSelect'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'

export function AssigneeFilter(): JSX.Element {
    const { assignee } = useValues(issueQueryOptionsLogic)
    const { setAssignee } = useActions(issueQueryOptionsLogic)

    return (
        <QuillAssigneeSelect
            ariaLabel="Assignee filter"
            assignee={assignee ?? null}
            clearActionLabel="Clear assignee filter"
            currentUserActionLabel="Assigned to me"
            onChange={setAssignee}
        >
            {(displayAssignee) => (
                <Button variant="outline" size="default">
                    <AssigneeIconDisplay assignee={displayAssignee} size="xsmall" />
                    <AssigneeLabelDisplay assignee={displayAssignee} size="xsmall" placeholder="Any assignee" />
                    <SelectTriggerIcon />
                </Button>
            )}
        </QuillAssigneeSelect>
    )
}
