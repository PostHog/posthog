import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { workflowLogic } from './workflowLogic'

export function WorkflowStartedSendingNotice(): JSX.Element | null {
    const { showStartedSendingNotice } = useValues(workflowLogic)
    const { dismissStartedSendingNotice } = useActions(workflowLogic)

    if (!showStartedSendingNotice) {
        return null
    }

    return (
        <LemonBanner
            type="success"
            action={{
                children: 'Dismiss',
                onClick: dismissStartedSendingNotice,
                'data-attr': 'workflow-started-sending-dismiss',
            }}
        >
            <strong>Started sending.</strong> This workflow was waiting for its email domain and is live now.
        </LemonBanner>
    )
}
