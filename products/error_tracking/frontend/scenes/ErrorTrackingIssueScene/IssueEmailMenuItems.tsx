import { useActions } from 'kea'

import { IconSend } from '@posthog/icons'

import { DropdownMenuItem } from 'lib/ui/quill'

import { openIssueWorkflow } from './issueWorkflow'
import { IssueAffectedBroadcastLogicProps, issueAffectedBroadcastLogic } from './ScenePanel/issueAffectedBroadcastLogic'

export interface IssueEmailMenuItemsProps extends IssueAffectedBroadcastLogicProps {
    className?: string
}

export function IssueEmailMenuItems({ className, ...props }: IssueEmailMenuItemsProps): JSX.Element {
    const { openModal } = useActions(issueAffectedBroadcastLogic(props))

    return (
        <>
            <DropdownMenuItem className={className} onClick={openModal} data-attr="error-tracking-issue-email-affected">
                <IconSend />
                Email people affected
            </DropdownMenuItem>
            <DropdownMenuItem
                className={className}
                onClick={() => openIssueWorkflow(props.issueId)}
                data-attr="error-tracking-issue-start-workflow"
            >
                <IconSend />
                Email anyone who hits this
            </DropdownMenuItem>
        </>
    )
}
