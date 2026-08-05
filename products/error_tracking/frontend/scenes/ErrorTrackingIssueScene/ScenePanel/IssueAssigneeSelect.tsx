import { IconChevronDown } from '@posthog/icons'

import { Button } from 'lib/ui/quill'

import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from '../../../components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../../../components/Assignee/AssigneeSelect'

export const IssueAssigneeSelect = ({
    assignee,
    onChange,
}: {
    assignee: ErrorTrackingIssueAssignee | null
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
}): JSX.Element => {
    return (
        <div>
            <AssigneeSelect assignee={assignee} onChange={onChange}>
                {(anyAssignee, isOpen) => (
                    <Button variant="default" size="default" data-state={isOpen ? 'open' : 'closed'}>
                        <AssigneeIconDisplay assignee={anyAssignee} size="small" />
                        <AssigneeLabelDisplay assignee={anyAssignee} size="small" />
                        <IconChevronDown />
                    </Button>
                )}
            </AssigneeSelect>
        </div>
    )
}
