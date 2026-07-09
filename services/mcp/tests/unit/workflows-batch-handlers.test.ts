import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Context } from '@/tools/types'
import { workflowsBlastRadius, workflowsRunBatch, workflowsScheduleCreate } from '@/tools/workflows/batch'

// Default per-team audience cap the mocked blast-radius endpoint returns unless a test overrides it.
const DEFAULT_LIMIT = 50_000

interface RequestArgs {
    method: string
    path: string
    body?: Record<string, unknown>
}

const BATCH_FILTERS = { properties: [{ key: 'email', value: 'is_set', type: 'person' }] }

/**
 * Mock context whose api.request dispatches by method+path:
 *  - GET  .../hog_flows/{id}/         -> the workflow (with the given trigger)
 *  - POST .../hog_flows/user_blast_radius/ -> the given blast radius
 *  - POST .../batch_jobs/ or .../schedules/ -> echoes the created resource
 */
function createMockContext(opts: {
    trigger: unknown
    blastRadius: { affected: number; total: number; limit?: number }
    status?: string
}): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn(async ({ method, path }: RequestArgs) => {
        if (method === 'GET' && /\/hog_flows\/[^/]+\/$/.test(path)) {
            return { id: 'wf-1', status: opts.status ?? 'active', trigger: opts.trigger }
        }
        if (method === 'POST' && path.endsWith('/user_blast_radius/')) {
            return { limit: DEFAULT_LIMIT, ...opts.blastRadius }
        }
        if (method === 'POST' && path.endsWith('/batch_jobs/')) {
            return { id: 'batch-1', status: 'queued' }
        }
        if (method === 'POST' && path.endsWith('/schedules/')) {
            return { id: 'sched-1', status: 'active' }
        }
        throw new Error(`unexpected request: ${method} ${path}`)
    })

    const context = {
        api: { request },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
    } as unknown as Context

    return { context, request }
}

function calls(request: ReturnType<typeof vi.fn>): RequestArgs[] {
    return request.mock.calls.map((c) => c[0] as RequestArgs)
}

const blastRadiusTool = workflowsBlastRadius()
const runBatchTool = workflowsRunBatch()
const scheduleCreateTool = workflowsScheduleCreate()

describe('workflows batch handlers', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    describe('workflows-blast-radius', () => {
        it('resolves the workflow trigger filters and sizes them, returning the count', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 42, total: 100 },
            })

            const result = await blastRadiusTool.handler(context, { workflow_id: 'wf-1' })

            const c = calls(request)
            expect(c[0]).toMatchObject({ method: 'GET', path: '/api/projects/1/hog_flows/wf-1/' })
            expect(c[1]).toMatchObject({
                method: 'POST',
                path: '/api/projects/1/hog_flows/user_blast_radius/',
                body: { filters: BATCH_FILTERS },
            })
            expect(result).toEqual({ affected: 42, total: 100, limit: DEFAULT_LIMIT })
        })
    })

    describe('workflows-run-batch', () => {
        it('fires the batch job with the trigger filters when the acknowledged count matches', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 10, total: 100 },
            })

            const result = await runBatchTool.handler(context, {
                workflow_id: 'wf-1',
                acknowledged_affected_count: 10,
                variables: { plan: 'pro' },
            })

            const batchCall = calls(request).find((c) => c.path.endsWith('/batch_jobs/'))
            expect(batchCall).toMatchObject({
                method: 'POST',
                path: '/api/projects/1/hog_flows/wf-1/batch_jobs/',
                body: { filters: BATCH_FILTERS, variables: { plan: 'pro' } },
            })
            expect(result).toMatchObject({ id: 'batch-1' })
        })

        it('omits variables from the body when none are given', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 10, total: 100 },
            })

            await runBatchTool.handler(context, { workflow_id: 'wf-1', acknowledged_affected_count: 10 })

            const batchCall = calls(request).find((c) => c.path.endsWith('/batch_jobs/'))
            expect(batchCall!.body).toEqual({ filters: BATCH_FILTERS })
        })

        it('rejects and does not fire when the acknowledged count is stale, surfacing the fresh count', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 25, total: 100 },
            })

            await expect(
                runBatchTool.handler(context, { workflow_id: 'wf-1', acknowledged_affected_count: 10 })
            ).rejects.toThrow(/25/)
            expect(calls(request).some((c) => c.path.endsWith('/batch_jobs/'))).toBe(false)
        })

        it('rejects and does not fire when the audience exceeds the per-team cap', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 5001, total: 1_000_000, limit: 5000 },
            })

            await expect(
                runBatchTool.handler(context, {
                    workflow_id: 'wf-1',
                    acknowledged_affected_count: 5001,
                })
            ).rejects.toThrow(/5000/)
            expect(calls(request).some((c) => c.path.endsWith('/batch_jobs/'))).toBe(false)
        })

        it('fires for a large audience that is within an elevated per-team cap', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 40_000, total: 1_000_000, limit: 50_000 },
            })

            const result = await runBatchTool.handler(context, {
                workflow_id: 'wf-1',
                acknowledged_affected_count: 40_000,
            })

            expect(calls(request).some((c) => c.path.endsWith('/batch_jobs/'))).toBe(true)
            expect(result).toMatchObject({ id: 'batch-1' })
        })

        it('rejects workflows whose trigger is not a batch trigger', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'event', filters: BATCH_FILTERS },
                blastRadius: { affected: 10, total: 100 },
            })

            await expect(
                runBatchTool.handler(context, { workflow_id: 'wf-1', acknowledged_affected_count: 10 })
            ).rejects.toThrow(/batch/)
            expect(calls(request).some((c) => c.path.endsWith('/batch_jobs/'))).toBe(false)
        })

        it('rejects a workflow that is not active, without firing', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 10, total: 100 },
                status: 'draft',
            })

            await expect(
                runBatchTool.handler(context, { workflow_id: 'wf-1', acknowledged_affected_count: 10 })
            ).rejects.toThrow(/enable/i)
            expect(calls(request).some((c) => c.path.endsWith('/batch_jobs/'))).toBe(false)
        })
    })

    describe('workflows-schedule-create', () => {
        it('creates the schedule for a batch trigger when the acknowledged count matches', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 3, total: 100 },
            })

            const result = await scheduleCreateTool.handler(context, {
                workflow_id: 'wf-1',
                rrule: 'FREQ=DAILY;INTERVAL=1',
                starts_at: '2026-06-01T00:00:00Z',
                timezone: 'UTC',
                acknowledged_affected_count: 3,
                variables: { plan: 'pro' },
            })

            const schedCall = calls(request).find((c) => c.path.endsWith('/schedules/'))
            expect(schedCall).toMatchObject({
                method: 'POST',
                path: '/api/projects/1/hog_flows/wf-1/schedules/',
                body: {
                    rrule: 'FREQ=DAILY;INTERVAL=1',
                    starts_at: '2026-06-01T00:00:00Z',
                    timezone: 'UTC',
                    variables: { plan: 'pro' },
                },
            })
            expect(result).toMatchObject({ id: 'sched-1' })
        })

        it('rejects a stale acknowledged count on a batch trigger without creating the schedule', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 50, total: 100 },
            })

            await expect(
                scheduleCreateTool.handler(context, {
                    workflow_id: 'wf-1',
                    rrule: 'FREQ=DAILY;INTERVAL=1',
                    starts_at: '2026-06-01T00:00:00Z',
                    acknowledged_affected_count: 3,
                })
            ).rejects.toThrow(/50/)
            expect(calls(request).some((c) => c.path.endsWith('/schedules/'))).toBe(false)
        })

        it('rejects scheduling a draft (non-active) workflow without creating the schedule', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'batch', filters: BATCH_FILTERS },
                blastRadius: { affected: 3, total: 100 },
                status: 'draft',
            })

            await expect(
                scheduleCreateTool.handler(context, {
                    workflow_id: 'wf-1',
                    rrule: 'FREQ=DAILY;INTERVAL=1',
                    starts_at: '2026-06-01T00:00:00Z',
                    acknowledged_affected_count: 3,
                })
            ).rejects.toThrow(/active/i)
            expect(calls(request).some((c) => c.path.endsWith('/schedules/'))).toBe(false)
        })

        it('rejects a non-batch trigger (schedule trigger no longer supported)', async () => {
            const { context, request } = createMockContext({
                trigger: { type: 'schedule' },
                blastRadius: { affected: 1, total: 1 },
            })

            await expect(
                scheduleCreateTool.handler(context, {
                    workflow_id: 'wf-1',
                    rrule: 'FREQ=DAILY;INTERVAL=1',
                    starts_at: '2026-06-01T00:00:00Z',
                    acknowledged_affected_count: 1,
                })
            ).rejects.toThrow(/batch/)
            expect(calls(request).some((c) => c.path.endsWith('/schedules/'))).toBe(false)
        })
    })
})
