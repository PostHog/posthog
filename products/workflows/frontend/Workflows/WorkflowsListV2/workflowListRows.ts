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
    /** Lowercased name, description, step names, subjects and senders, built once for text search. */
    searchText: string
}

export interface EmailTemplateRow {
    kind: 'email_template'
    id: string
    name: string
    updatedAt: string
    template: MessageTemplateListRowApi
    searchText: string
}

export type WorkflowListRow = WorkflowRow | EmailTemplateRow

// `Owner:` must start the text, a line (after indent, `-`, `*`, `•` or `>`) or a clause, so `Co-owner:`
// and `Previous owner:` don't count.
const OWNER_PATTERN = /(?<=^[\s>*•-]*|[.(,;|]\s*)owner:\s*@([\w.-]+)/gim

function creatorHandle(user: UserBasicApi | null): string | null {
    if (!user) {
        return null
    }
    return (user.first_name || user.email.split('@')[0]).toLowerCase() || null
}

function workflowOwners(workflow: HogFlowListRowApi): string[] {
    const explicit = [...(workflow.description ?? '').matchAll(OWNER_PATTERN)]
        .map((match) => match[1].replace(/[.-]+$/, '').toLowerCase())
        .filter(Boolean)
    if (explicit.length) {
        return [...new Set(explicit)]
    }
    const creator = creatorHandle(workflow.created_by)
    return creator ? [creator] : []
}

function workflowHealth(workflow: HogFlowListRowApi): WorkflowHealth {
    const totals = workflow.last_7_days
    if (totals && totals.failed > 0) {
        return 'failing'
    }
    if (totals && totals.succeeded > 0) {
        return 'healthy'
    }
    return 'idle'
}

const unique = (values: string[]): string[] => [...new Set(values)]

type EmailSteps = HogFlowListRowApi['email_steps']

function stepSubjects(steps: EmailSteps): string[] {
    return unique(steps.map((step) => step.subject).filter(Boolean))
}

function stepAddresses(steps: EmailSteps): string[] {
    return unique(steps.flatMap((step) => step.from_addresses))
}

export function rowSubjects(row: WorkflowListRow): string[] {
    if (row.kind === 'email_template') {
        return row.template.subject ? [row.template.subject] : []
    }
    return stepSubjects(row.workflow.email_steps)
}

export function rowFromAddresses(row: WorkflowListRow): string[] {
    return row.kind === 'email_template'
        ? unique([...row.template.from_addresses])
        : stepAddresses(row.workflow.email_steps)
}

function searchTextOf(parts: (string | null | undefined)[]): string {
    return parts.filter(Boolean).join('\n').toLowerCase()
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
                searchText: searchTextOf([
                    workflow.name,
                    workflow.description,
                    ...workflow.email_steps.map((step) => step.name),
                    ...stepSubjects(workflow.email_steps),
                    ...stepAddresses(workflow.email_steps),
                ]),
            })
        ),
        ...templates.map(
            (template): EmailTemplateRow => ({
                kind: 'email_template',
                id: template.id,
                name: template.name,
                updatedAt: template.updated_at,
                template,
                searchText: searchTextOf([
                    template.name,
                    template.description,
                    template.subject,
                    ...template.from_addresses,
                ]),
            })
        ),
    ]
    return rows.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
}
