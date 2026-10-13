import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { Assignee, assigneeSelectLogic } from './assigneeSelectLogic'
import { QuillAssigneeDropdown } from './QuillAssigneeDropdown'

export const QuillAssigneeSelect = ({
    ariaLabel = 'Assignee',
    assignee,
    children,
    clearActionLabel = 'Remove assignee',
    currentUserActionLabel = 'Assign to me',
    onChange,
}: {
    ariaLabel?: string
    assignee: ErrorTrackingIssue['assignee']
    children: (assignee: Assignee, isOpen: boolean) => JSX.Element
    clearActionLabel?: string
    currentUserActionLabel?: string
    onChange: (assignee: ErrorTrackingIssue['assignee']) => void
}): JSX.Element => {
    const { ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const { resolveAssignee } = useValues(assigneeSelectLogic)
    const [showPopover, setShowPopover] = useState(false)
    const resolvedAssignee = useMemo(() => resolveAssignee(assignee), [assignee, resolveAssignee])

    const _onChange = (value: ErrorTrackingIssue['assignee']): void => {
        setShowPopover(false)
        onChange(value)
    }

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return (
        <QuillAssigneeDropdown
            ariaLabel={ariaLabel}
            assignee={assignee}
            clearActionLabel={clearActionLabel}
            currentUserActionLabel={currentUserActionLabel}
            onChange={_onChange}
            open={showPopover}
            onOpenChange={setShowPopover}
            trigger={children(resolvedAssignee, showPopover)}
        />
    )
}
