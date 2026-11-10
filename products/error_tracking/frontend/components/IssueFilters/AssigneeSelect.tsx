import { Button, SelectTriggerIcon } from 'lib/ui/quill'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from '../Assignee/AssigneeDisplay'
import { QuillAssigneeSelect } from '../Assignee/QuillAssigneeSelect'

export function AssigneeSelect({
    assignee,
    onChange,
}: {
    assignee: ErrorTrackingIssue['assignee']
    onChange: (assignee: ErrorTrackingIssue['assignee']) => void
}): JSX.Element {
    return (
        <QuillAssigneeSelect
            ariaLabel="Assignee filter"
            assignee={assignee ?? null}
            clearActionLabel="Clear assignee filter"
            currentUserActionLabel="Assigned to me"
            onChange={onChange}
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
