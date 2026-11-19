import posthog from 'posthog-js'

import { workflowEmailSandboxProvision, workflowEmailSandboxStatus } from '../generated/api'
import type { WorkflowEmailSandboxStatusApi } from '../generated/api.schemas'
import type { HogFlow } from '../Workflows/hogflows/types'

export type SandboxSenderSurface = 'first_run' | 'inserted_step' | 'sender_control' | 'channels'

export function canAdoptSandboxSender(status: WorkflowEmailSandboxStatusApi | null | undefined): boolean {
    return !!status?.adoption_enabled && !status.organization_blocked && !!status.from_address
}

export function isLiveOnSandboxSender(workflow: Pick<HogFlow, 'status' | 'actions'>): boolean {
    return workflow.status === 'active' && (workflow.actions ?? []).some((action) => action.type === 'email_sandbox')
}

// Publishing promotes the staged draft over an active workflow, so a step it moves onto the test sender
// goes live, even when another step already sends from it.
export function publishMovesStepsToSandboxSender(live: HogFlow): boolean {
    if (live.status !== 'active' || !live.draft) {
        return false
    }
    const liveSandboxIds = new Set(live.actions.filter((a) => a.type === 'email_sandbox').map((a) => a.id))
    return (live.draft.actions ?? []).some((a) => a.type === 'email_sandbox' && !liveSandboxIds.has(a.id))
}

export async function provisionSandboxSender(teamId: string, surface: SandboxSenderSurface): Promise<number> {
    const { integration_id } = await workflowEmailSandboxProvision(teamId)
    // pinned: analytics event name
    posthog.capture('workflows sandbox sender provisioned', { surface })
    return integration_id
}

export async function readySandboxSender(teamId: string, surface: SandboxSenderSurface): Promise<boolean> {
    try {
        const status = await workflowEmailSandboxStatus(teamId)
        if (!canAdoptSandboxSender(status)) {
            return false
        }
        if (status.integration_id === null) {
            await provisionSandboxSender(teamId, surface)
        }
        return true
    } catch {
        return false
    }
}
