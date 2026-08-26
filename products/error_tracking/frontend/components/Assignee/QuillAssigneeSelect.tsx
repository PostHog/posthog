import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { Assignee, assigneeSelectLogic } from './assigneeSelectLogic'
import { QuillAssigneeDropdown } from './QuillAssigneeDropdown'

export const QuillAssigneeSelect = ({
    assignee,
    onChange,
    children,
}: {
    assignee: ErrorTrackingIssue['assignee']
    onChange: (assignee: ErrorTrackingIssue['assignee']) => void
    children: (assignee: Assignee, isOpen: boolean) => JSX.Element
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
            assignee={assignee}
            onChange={_onChange}
            open={showPopover}
            onOpenChange={setShowPopover}
            trigger={children(resolvedAssignee, showPopover)}
        />
    )
}
