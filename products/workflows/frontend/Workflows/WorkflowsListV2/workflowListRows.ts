import type {
    HogFlowListSummaryApi,
    UserBasicApi,
    WorkflowStatsRowApi,
} from 'products/workflows/frontend/generated/api.schemas'

export type WorkflowHealth = 'failing' | 'healthy' | 'idle'

export interface WorkflowRunCounts {
    succeeded: number
    failed: number
}

export interface WorkflowListRow {
    id: string
    name: string
    workflow: HogFlowListSummaryApi
    triggerType: string | null
    owners: string[]
    /** Null while the metrics load, and when they fail. */
    last7Days: WorkflowRunCounts | null
    health: WorkflowHealth
    searchText: string
}

// `Owner:` must start the text, a line (after indent, `-`, `*`, `•` or `>`) or a clause, so `Co-owner:`
// and `Previous owner:` don't count.
const OWNER_PATTERN = /(?<=^[\s>*•-]*|[.(,;|]\s*)owner:\s*@([\w.-]+)/gim

export function creatorHandle(user: Pick<UserBasicApi, 'first_name' | 'email'> | null): string | null {
    if (!user) {
        return null
    }
    return (user.first_name || user.email.split('@')[0]).toLowerCase() || null
}

function workflowOwners(workflow: HogFlowListSummaryApi): string[] {
    const explicit = [...(workflow.description ?? '').matchAll(OWNER_PATTERN)]
        .map((match) => match[1].replace(/[.-]+$/, '').toLowerCase())
        .filter(Boolean)
    if (explicit.length) {
        return [...new Set(explicit)]
    }
    const creator = creatorHandle(workflow.created_by)
    return creator ? [creator] : []
}

function triggerTypeOf(trigger: unknown): string | null {
    if (trigger && typeof trigger === 'object' && 'type' in trigger && typeof trigger.type === 'string') {
        return trigger.type
    }
    return null
}

function healthOf(counts: WorkflowRunCounts | null): WorkflowHealth {
    if (counts && counts.failed > 0) {
        return 'failing'
    }
    if (counts && counts.succeeded > 0) {
        return 'healthy'
    }
    return 'idle'
}

export function buildWorkflowListRows(
    workflows: HogFlowListSummaryApi[],
    metrics: WorkflowStatsRowApi[] | null
): WorkflowListRow[] {
    const countsById = new Map(metrics?.map((row) => [row.workflow_id, row]))
    return workflows
        .map((workflow): WorkflowListRow => {
            const stats = countsById.get(workflow.id)
            const last7Days = metrics ? { succeeded: stats?.succeeded ?? 0, failed: stats?.failed ?? 0 } : null
            return {
                id: workflow.id,
                name: workflow.name ?? '',
                workflow,
                triggerType: triggerTypeOf(workflow.trigger),
                owners: workflowOwners(workflow),
                last7Days,
                health: healthOf(last7Days),
                searchText: [workflow.name, workflow.description].filter(Boolean).join('\n').toLowerCase(),
            }
        })
        .sort((a, b) => Date.parse(b.workflow.updated_at) - Date.parse(a.workflow.updated_at))
}
