import { LemonDialog } from '@posthog/lemon-ui'

import type { HogFlow } from './hogflows/types'
import {
    STATUS_CHANGE_CANCEL_ATTR,
    STATUS_CHANGE_CONFIRM_ATTR,
    WorkflowStatusChangeSurface,
    WorkflowStatusChangeTarget,
    statusChangeConsequence,
    statusChangeTitle,
    trackStatusChangeConfirmed,
    trackStatusChangeShown,
    triggerRecap,
} from './workflowStatusChange'

export function confirmWorkflowStatusChange({
    workflowId,
    status,
    trigger,
    surface,
    onConfirm,
}: {
    workflowId: string
    status: WorkflowStatusChangeTarget
    trigger: HogFlow['trigger']
    surface: WorkflowStatusChangeSurface
    onConfirm: () => void
}): void {
    trackStatusChangeShown(workflowId, surface, status)
    // The dialog stays clickable while it animates closed, and a second click would save twice.
    let confirmed = false
    LemonDialog.open({
        title: statusChangeTitle(status),
        maxWidth: '36rem',
        description: (
            <div className="flex flex-col gap-2">
                <p className="mb-0">{statusChangeConsequence(status)}</p>
                <p className="mb-0">
                    <strong>Trigger:</strong> {triggerRecap(trigger)}
                </p>
            </div>
        ),
        primaryButton: {
            children: 'Yes, continue',
            type: 'primary',
            status: status === 'active' ? 'default' : 'danger',
            'data-attr': STATUS_CHANGE_CONFIRM_ATTR[status],
            onClick: () => {
                if (confirmed) {
                    return
                }
                confirmed = true
                trackStatusChangeConfirmed(workflowId, surface, status)
                onConfirm()
            },
        },
        secondaryButton: {
            children: 'Actually no',
            type: 'secondary',
            'data-attr': STATUS_CHANGE_CANCEL_ATTR,
        },
    })
}
