import posthog from 'posthog-js'

import { ApiConfig } from 'lib/api'

import { hogFlowsRetrieve, workflowEmailSandboxProvision, workflowEmailSandboxStatus } from '../generated/api'
import type { WorkflowEmailSandboxStatusApi } from '../generated/api.schemas'
import type { HogFlow } from '../Workflows/hogflows/types'

export type SandboxSenderSurface = 'first_run' | 'inserted_step' | 'sender_control' | 'channels'

export function canAdoptSandboxSender(status: WorkflowEmailSandboxStatusApi | null | undefined): boolean {
    return !!status?.adoption_enabled && !status.organization_blocked && !!status.from_address
}

export function isLiveOnSandboxSender(workflow: Pick<HogFlow, 'status' | 'actions'>): boolean {
    return workflow.status === 'active' && (workflow.actions ?? []).some((action) => action.type === 'email_sandbox')
}

// The sender checks read the server's copy, because another tab, an agent or the API may have changed the
// steps since this page loaded. Null when it can't be read: the page's own copy may be the stale one, so a
// caller stops rather than check that.
export async function fetchStoredWorkflow(id: string): Promise<HogFlow | null> {
    try {
        const stored = (await hogFlowsRetrieve(String(ApiConfig.getCurrentTeamId()), id)) as unknown as HogFlow
        // A response without steps or a stamp would read as "no test sender steps" and skip the warning.
        return Array.isArray(stored?.actions) && typeof stored.updated_at === 'string' ? stored : null
    } catch {
        return null
    }
}

// For a publish preview from a worker that predates `moves_to_sandbox_sender`. The live steps and the status
// can change elsewhere without the editor seeing it, so any test sender step in the draft counts.
export function draftUsesSandboxSender(workflow: Pick<HogFlow, 'draft'>): boolean {
    return (workflow.draft?.actions ?? []).some((a) => a.type === 'email_sandbox')
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
