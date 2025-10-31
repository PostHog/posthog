import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuOpenIndicator } from 'lib/ui/DropdownMenu/DropdownMenu'

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
            {(anyAssignee, isOpen) => (
                <ButtonPrimitive
                    menuItem
                    fullWidth
                    disabled={disabled}
                    className="flex justify-between"
                    data-state={isOpen ? 'open' : 'closed'}
                    variant="panel"
                >
                    <div className="flex items-center">
                        <AssigneeIconDisplay assignee={anyAssignee} size="small" />
                        <AssigneeLabelDisplay assignee={anyAssignee} className="ml-1" size="small" />
                    </div>
                    {!disabled && <DropdownMenuOpenIndicator />}
                </ButtonPrimitive>
            )}
        </AssigneeSelect>
    )
}
