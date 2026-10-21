import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { MessagingSetupTabKey } from '../messagingTabs'
import { workflowsSetupGuideLogic } from './workflowsSetupGuideLogic'

/** The setup state of one Messaging menu item: done, or what is still open. */
export function MessagingSetupMenuStatus({ tab }: { tab: MessagingSetupTabKey }): JSX.Element | null {
    const { steps } = useValues(workflowsSetupGuideLogic)

    if (!steps) {
        return null
    }
    const isDone = (key: string): boolean => steps.some((step) => step.key === key && step.done)

    if (tab === 'channels') {
        if (isDone('domain')) {
            return <IconCheckCircle className="text-success" />
        }
        return (
            <LemonTag size="small" type="warning">
                {isDone('channel') ? 'Verify' : 'Set up'}
            </LemonTag>
        )
    }
    if (tab === 'opt-outs') {
        return isDone('opt-outs') ? (
            <IconCheckCircle className="text-success" />
        ) : (
            <LemonTag size="small" type="warning">
                Set up
            </LemonTag>
        )
    }
    return null
}
