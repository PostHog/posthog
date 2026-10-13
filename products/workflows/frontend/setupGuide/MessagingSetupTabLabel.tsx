import { useValues } from 'kea'

import { LemonBadge } from '@posthog/lemon-ui'

import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** The "Messaging" tab label, with a dot while a person who chose messaging has setup steps open. */
export function MessagingSetupTabLabel(): JSX.Element {
    const { showMessagingReminder } = useValues(workflowsSetupGuideLogic)

    return (
        <span className="flex items-center gap-1">
            <span>Messaging</span>
            {showMessagingReminder && <LemonBadge status="warning" size="small" position="none" />}
        </span>
    )
}
