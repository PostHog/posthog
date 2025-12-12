import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'

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
        <div>
            <AssigneeSelect assignee={assignee} onChange={onChange}>
                {(anyAssignee, isOpen) => (
                    <ButtonPrimitive disabled={disabled} data-state={isOpen ? 'open' : 'closed'}>
                        <div className="flex items-center">
                            <AssigneeIconDisplay assignee={anyAssignee} size="small" />
                            <AssigneeLabelDisplay assignee={anyAssignee} className="ml-1" size="small" />
                        </div>
                        {!disabled && <MenuOpenIndicator className="ml-auto" />}
                    </ButtonPrimitive>
                )}
            </AssigneeSelect>
        </div>
    )
}
