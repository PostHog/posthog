import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

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

    return <ErrorTrackingAssigneeSelectButton assignee={assignee ?? null} onChange={(value) => setAssignee(value)} />
}
