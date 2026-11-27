import { useActions } from 'kea'

import { IconSend } from '@posthog/icons'

import { DropdownMenuItem } from 'lib/ui/quill'

import {
    MessageAudienceSpot,
    useMessageAudienceAttempts,
} from 'products/workflows/frontend/MessageAudience/MessageAudienceSpot'

import { ISSUE_WORKFLOW_SOURCE, openIssueWorkflow } from './issueWorkflow'
import {
    ISSUE_AFFECTED_SOURCE,
    IssueAffectedBroadcastLogicProps,
    issueAffectedBroadcastLogic,
} from './ScenePanel/issueAffectedBroadcastLogic'

export function IssueEmailMenuItems(props: IssueAffectedBroadcastLogicProps): JSX.Element {
    const { openModal } = useActions(issueAffectedBroadcastLogic(props))
    const attempts = useMessageAudienceAttempts()

    return (
        <>
            <DropdownMenuItem
                onClick={() => openModal(attempts.idFor('broadcast'))}
                data-attr="error-tracking-issue-email-affected"
            >
                <IconSend />
                <MessageAudienceSpot attempts={attempts} source={ISSUE_AFFECTED_SOURCE} destination="broadcast">
                    Email people affected
                </MessageAudienceSpot>
            </DropdownMenuItem>
            <DropdownMenuItem
                onClick={() => openIssueWorkflow(props.issueId, attempts.idFor('workflow'))}
                data-attr="error-tracking-issue-start-workflow"
            >
                <IconSend />
                <MessageAudienceSpot attempts={attempts} source={ISSUE_WORKFLOW_SOURCE} destination="workflow">
                    Email anyone who hits this
                </MessageAudienceSpot>
            </DropdownMenuItem>
        </>
    )
}
