import type {
    HogFlowListSummaryApi,
    UserBasicApi,
    WorkflowStatsRowApi,
} from 'products/workflows/frontend/generated/api.schemas'

export const FIXTURE_USERS: Record<'ada' | 'lin', UserBasicApi> = {
    ada: {
        id: 1,
        uuid: '0190a1b2-0000-7000-8000-00000000a001',
        first_name: 'Ada',
        email: 'ada@example.com',
        hedgehog_config: null,
    },
    lin: {
        id: 2,
        uuid: '0190a1b2-0000-7000-8000-00000000a002',
        first_name: '',
        email: 'lin.ops@example.com',
        hedgehog_config: null,
    },
}

export function buildWorkflowRow(
    overrides: Partial<HogFlowListSummaryApi> & Pick<HogFlowListSummaryApi, 'id'>
): HogFlowListSummaryApi {
    return {
        name: `Workflow ${overrides.id}`,
        description: '',
        version: 1,
        status: 'draft',
        type: 'automation',
        origin_product: null,
        trigger: { type: 'event' },
        created_by: FIXTURE_USERS.ada,
        created_at: '2026-08-01T10:00:00Z',
        updated_at: '2026-08-01T10:00:00Z',
        user_access_level: 'editor',
        ...overrides,
    }
}

/** A small invented project with a mix of statuses, types, triggers and owners. */
export const FIXTURE_WORKFLOWS: HogFlowListSummaryApi[] = [
    buildWorkflowRow({
        id: 'wf-welcome',
        name: 'Welcome series',
        description: 'Owner: @maya. Greets new sign-ups.',
        status: 'active',
        type: 'messaging',
        updated_at: '2026-09-20T09:00:00Z',
    }),
    buildWorkflowRow({
        id: 'wf-renewal',
        name: 'Renewal reminder',
        description: 'Reminds customers a week before their plan renews.',
        status: 'draft',
        type: 'messaging',
        updated_at: '2026-09-18T09:00:00Z',
    }),
    buildWorkflowRow({
        id: 'wf-sync',
        name: 'Sync accounts to CRM',
        description:
            'Owner: @kim. Copies new accounts and plan changes to the CRM every night, retries failed rows once, and emails a summary to the ops inbox.',
        status: 'draft',
        type: 'automation',
        trigger: { type: 'schedule' },
        created_by: FIXTURE_USERS.lin,
        updated_at: '2026-09-10T09:00:00Z',
    }),
    buildWorkflowRow({
        id: 'wf-old-promo',
        name: 'Spring promo',
        status: 'archived',
        type: 'messaging',
        updated_at: '2026-04-01T09:00:00Z',
    }),
]

/** Last-7-days counts for the fixture workflows. `wf-old-promo` had no runs, so it has no row. */
export const FIXTURE_METRICS: WorkflowStatsRowApi[] = [
    { workflow_id: 'wf-renewal', succeeded: 3, failed: 2 },
    { workflow_id: 'wf-welcome', succeeded: 40, failed: 0 },
    { workflow_id: 'wf-sync', succeeded: 0, failed: 0 },
]

export function paginated<T>(
    results: T[],
    next: string | null = null
): {
    count: number
    next: string | null
    previous: null
    results: T[]
} {
    return { count: results.length, next, previous: null, results }
}
