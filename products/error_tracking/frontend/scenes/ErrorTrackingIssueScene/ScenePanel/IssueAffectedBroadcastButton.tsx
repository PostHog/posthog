import { useActions } from 'kea'

import { IconSend } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { IssueAffectedBroadcastLogicProps, issueAffectedBroadcastLogic } from './issueAffectedBroadcastLogic'
import { IssueAffectedBroadcastModal } from './IssueAffectedBroadcastModal'

export function IssueAffectedBroadcastButton(props: IssueAffectedBroadcastLogicProps): JSX.Element {
    const { openModal } = useActions(issueAffectedBroadcastLogic(props))
    return (
        <>
            <ButtonPrimitive fullWidth onClick={openModal} data-attr="issue-panel-email-affected">
                <IconSend />
                Email the people affected
            </ButtonPrimitive>
            <IssueAffectedBroadcastModal {...props} />
        </>
    )
}
