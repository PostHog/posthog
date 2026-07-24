import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Button } from 'lib/ui/quill'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { AssigneeIconDisplay, AssigneeLabelDisplay } from './AssigneeDisplay'
import { AssigneeSelect } from './AssigneeSelect'

type ErrorTrackingAssigneeSelectButtonProps = {
    assignee: ErrorTrackingIssue['assignee']
    onChange: (assignee: ErrorTrackingIssue['assignee']) => void
    placeholder?: string
    fullWidth?: boolean
}

export function ErrorTrackingAssigneeSelectButton({
    assignee,
    onChange,
    placeholder = 'Any assignee',
    fullWidth,
}: ErrorTrackingAssigneeSelectButtonProps): JSX.Element {
    return (
        <AssigneeSelect assignee={assignee ?? null} onChange={onChange} fullWidth={fullWidth}>
            {(displayAssignee) => (
                <LemonButton type="secondary" size="small" fullWidth={fullWidth}>
                    <span className="flex items-center gap-1 min-w-0">
                        <AssigneeIconDisplay assignee={displayAssignee} size="small" />
                        <AssigneeLabelDisplay
                            assignee={displayAssignee}
                            placeholder={placeholder}
                            size="small"
                            className="truncate"
                        />
                    </span>
                </LemonButton>
            )}
        </AssigneeSelect>
    )
}

/** Issues tab filter bar — wires shared button to issueQueryOptionsLogic. */
export function AssigneeFilter(): JSX.Element {
    const { assignee } = useValues(issueQueryOptionsLogic)
    const { setAssignee } = useActions(issueQueryOptionsLogic)

    return (
        <AssigneeSelect assignee={assignee ?? null} onChange={(value) => setAssignee(value)}>
            {(displayAssignee, isOpen) => (
                <Button variant="outline" size="default" aria-expanded={isOpen}>
                    <AssigneeIconDisplay assignee={displayAssignee} size="small" />
                    <AssigneeLabelDisplay
                        assignee={displayAssignee}
                        placeholder="Any assignee"
                        className="max-w-40 truncate"
                    />
                    <IconChevronDown className="size-4" />
                </Button>
            )}
        </AssigneeSelect>
    )
}
