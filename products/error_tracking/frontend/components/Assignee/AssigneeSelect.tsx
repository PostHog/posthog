import { useActions } from 'kea'
import { useEffect, useState } from 'react'

import { LemonDropdown } from '@posthog/lemon-ui'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeResolver } from './AssigneeDisplay'
import { AssigneeDropdown } from './AssigneeDropdown'
import { Assignee, assigneeSelectLogic } from './assigneeSelectLogic'

export const AssigneeSelect = ({
    assignee,
    onChange,
    children,
    fullWidth = false,
}: {
    assignee: ErrorTrackingIssue['assignee']
    onChange: (assignee: ErrorTrackingIssue['assignee']) => void
    children: (assignee: Assignee, isOpen: boolean) => JSX.Element
    /** When true, the trigger fills its container (e.g. a grid column). Default is content width for filter bars. */
    fullWidth?: boolean
}): JSX.Element => {
    const { setSearch, ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const [showPopover, setShowPopover] = useState(false)

    const _onChange = (value: ErrorTrackingIssue['assignee']): void => {
        setSearch('')
        setShowPopover(false)
        onChange(value)
    }

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            onVisibilityChange={(visible) => setShowPopover(visible)}
            overlay={<AssigneeDropdown assignee={assignee} onChange={_onChange} />}
        >
            <div className={fullWidth ? 'w-full' : 'w-fit'}>
                <AssigneeResolver assignee={assignee}>
                    {({ assignee: resolvedAssignee }) => children(resolvedAssignee, showPopover)}
                </AssigneeResolver>
            </div>
        </LemonDropdown>
    )
}
