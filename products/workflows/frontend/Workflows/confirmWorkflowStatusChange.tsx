import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import type { HogFlow } from './hogflows/types'
import { triggerEventNames, triggerLeadIn } from './overview/workflowOverviewSummary'

export type WorkflowStatusChangeSurface = 'editor' | 'list'

function triggerRecap(trigger: HogFlow['trigger']): string {
    if (!trigger) {
        return triggerLeadIn(trigger)
    }
    const eventNames = triggerEventNames(trigger)
    return `${triggerLeadIn(trigger)}${eventNames.length > 0 ? `: ${eventNames.join(', ')}` : ''}.`
}

export function confirmWorkflowStatusChange({
    workflowId,
    status,
    trigger,
    surface,
    onConfirm,
}: {
    workflowId: string
    status: 'active' | 'draft'
    trigger: HogFlow['trigger']
    surface: WorkflowStatusChangeSurface
    onConfirm: () => void
}): void {
    const enabling = status === 'active'
    // pinned: analytics event names and property values
    posthog.capture('workflows status change confirmation shown', { workflow_id: workflowId, surface, status })
    // The dialog stays clickable while it animates closed, and a second click would save twice.
    let confirmed = false
    LemonDialog.open({
        title: `Are you sure you want to ${enabling ? 'enable' : 'disable'} this workflow?`,
        maxWidth: '36rem',
        description: (
            <div className="flex flex-col gap-2">
                <p className="mb-0">
                    <strong>Trigger:</strong> {triggerRecap(trigger)}
                </p>
                <p className="mb-0">
                    {enabling
                        ? 'From now on, new runs start each time this trigger fires.'
                        : "From now on, this trigger doesn't start new runs. In-progress runs will be canceled and users within the workflow won't continue."}
                </p>
            </div>
        ),
        primaryButton: {
            children: 'Yes, continue',
            status: enabling ? 'default' : 'danger',
            'data-attr': enabling ? 'workflow-confirm-enable' : 'workflow-confirm-disable',
            onClick: () => {
                if (confirmed) {
                    return
                }
                confirmed = true
                posthog.capture('workflows status change confirmed', { workflow_id: workflowId, surface, status })
                onConfirm()
            },
        },
        secondaryButton: {
            children: 'Actually no',
            'data-attr': 'workflow-cancel-status-change',
        },
    })
}
