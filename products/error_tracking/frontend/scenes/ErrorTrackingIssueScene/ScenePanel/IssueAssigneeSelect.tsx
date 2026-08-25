import { Button, SelectTriggerIcon } from 'lib/ui/quill'

import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from '../../../components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../../../components/Assignee/AssigneeSelect'

export const IssueAssigneeSelect = ({
    assignee,
    disabled,
    onChange,
}: {
    assignee: ErrorTrackingIssueAssignee | null
    disabled: boolean
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
}): JSX.Element => {
    return (
        <AssigneeSelect assignee={assignee} onChange={onChange}>
            {(anyAssignee) => (
                <Button variant="outline" disabled={disabled}>
                    <AssigneeIconDisplay assignee={anyAssignee} size="xsmall" />
                    <AssigneeLabelDisplay assignee={anyAssignee} className="text-xs text-secondary" size="xsmall" />
                    {!disabled && <SelectTriggerIcon />}
                </Button>
            )}
        </AssigneeSelect>
    )
}
