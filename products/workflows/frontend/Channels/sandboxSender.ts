import posthog from 'posthog-js'

import { workflowEmailSandboxProvision, workflowEmailSandboxStatus } from '../generated/api'
import type { WorkflowEmailSandboxStatusApi } from '../generated/api.schemas'

export type SandboxSenderSurface = 'first_run' | 'inserted_step' | 'sender_control' | 'channels'

export function canAdoptSandboxSender(status: WorkflowEmailSandboxStatusApi | null | undefined): boolean {
    return !!status?.adoption_enabled && !status.organization_blocked && !!status.from_address
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
