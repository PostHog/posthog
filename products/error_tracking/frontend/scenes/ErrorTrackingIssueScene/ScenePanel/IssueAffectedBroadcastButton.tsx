import { useActions } from 'kea'

import { IconSend } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { messageAudienceAccessDisabledReason } from 'products/workflows/frontend/MessageAudience/messageAudience'

import { IssueAffectedBroadcastLogicProps, issueAffectedBroadcastLogic } from './issueAffectedBroadcastLogic'
import { IssueAffectedBroadcastModal } from './IssueAffectedBroadcastModal'

export function IssueAffectedBroadcastButton(props: IssueAffectedBroadcastLogicProps): JSX.Element {
    const { openModal } = useActions(issueAffectedBroadcastLogic(props))
    const accessDisabledReason = messageAudienceAccessDisabledReason()
    return (
        <>
            <ButtonPrimitive
                fullWidth
                onClick={openModal}
                disabledReasons={accessDisabledReason ? { [accessDisabledReason]: true } : {}}
                data-attr="issue-panel-email-affected"
            >
                <IconSend />
                Email people affected
            </ButtonPrimitive>
            <IssueAffectedBroadcastModal {...props} />
        </>
    )
}
