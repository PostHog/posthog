import type { MessageTemplateListRowApi } from 'products/messaging/frontend/generated/api.schemas'
import type { HogFlowListRowApi, UserBasicApi } from 'products/workflows/frontend/generated/api.schemas'

export type WorkflowHealth = 'failing' | 'healthy' | 'idle'

export interface WorkflowRow {
    kind: 'workflow'
    id: string
    name: string
    updatedAt: string
    workflow: HogFlowListRowApi
    /** Explicit `Owner: @handle` names from the description, else the creator's handle. */
    owners: string[]
    health: WorkflowHealth
}

export interface EmailTemplateRow {
    kind: 'email_template'
    id: string
    name: string
    updatedAt: string
    template: MessageTemplateListRowApi
}

export type WorkflowListRow = WorkflowRow | EmailTemplateRow

const OWNER_PATTERN = /owner:\s*@([\w.-]+)/gi

function creatorHandle(user: UserBasicApi | null): string | null {
    if (!user) {
        return null
    }
    return (user.first_name || user.email.split('@')[0]).toLowerCase() || null
}

export function workflowOwners(workflow: HogFlowListRowApi): string[] {
    const explicit = [...(workflow.description ?? '').matchAll(OWNER_PATTERN)]
        .map((match) => match[1].replace(/[.-]+$/, '').toLowerCase())
        .filter(Boolean)
    if (explicit.length) {
        return [...new Set(explicit)]
    }
    const creator = creatorHandle(workflow.created_by)
    return creator ? [creator] : []
}

export function workflowHealth(workflow: HogFlowListRowApi): WorkflowHealth {
    const totals = workflow.last_7_days
    if (totals && totals.failed > 0) {
        return 'failing'
    }
    if (totals && totals.succeeded > 0) {
        return 'healthy'
    }
    return 'idle'
}

export function rowCreatedBy(row: WorkflowListRow): UserBasicApi | null {
    return row.kind === 'workflow' ? row.workflow.created_by : row.template.created_by
}

/** Workflows and email templates in one list, most recently updated first. */
export function buildWorkflowListRows(
    workflows: HogFlowListRowApi[],
    templates: MessageTemplateListRowApi[]
): WorkflowListRow[] {
    const rows: WorkflowListRow[] = [
        ...workflows.map(
            (workflow): WorkflowRow => ({
                kind: 'workflow',
                id: workflow.id,
                name: workflow.name ?? '',
                updatedAt: workflow.updated_at,
                workflow,
                owners: workflowOwners(workflow),
                health: workflowHealth(workflow),
            })
        ),
        ...templates.map(
            (template): EmailTemplateRow => ({
                kind: 'email_template',
                id: template.id,
                name: template.name,
                updatedAt: template.updated_at,
                template,
            })
        ),
    ]
    return rows.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
}
