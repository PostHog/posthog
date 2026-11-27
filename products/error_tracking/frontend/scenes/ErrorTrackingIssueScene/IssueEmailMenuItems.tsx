import { useActions } from 'kea'

import { IconSend } from '@posthog/icons'

import { DropdownMenuItem } from 'lib/ui/quill'

import { MessageAudienceShown } from 'products/workflows/frontend/MessageAudience/MessageAudienceShown'

import { ISSUE_WORKFLOW_SOURCE, openIssueWorkflow } from './issueWorkflow'
import {
    AFFECTED_SOURCE,
    IssueAffectedBroadcastLogicProps,
    issueAffectedBroadcastLogic,
} from './ScenePanel/issueAffectedBroadcastLogic'

export function IssueEmailMenuItems(props: IssueAffectedBroadcastLogicProps): JSX.Element {
    const { openModal } = useActions(issueAffectedBroadcastLogic(props))

    return (
        <>
            <MessageAudienceShown source={AFFECTED_SOURCE} destination="broadcast" />
            <MessageAudienceShown source={ISSUE_WORKFLOW_SOURCE} destination="workflow" />
            <DropdownMenuItem onClick={openModal} data-attr="error-tracking-issue-email-affected">
                <IconSend />
                Email people affected
            </DropdownMenuItem>
            <DropdownMenuItem
                onClick={() => openIssueWorkflow(props.issueId)}
                data-attr="error-tracking-issue-start-workflow"
            >
                <IconSend />
                Email anyone who hits this
            </DropdownMenuItem>
        </>
    )
}
