import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

/**
 * Mirrors `CDP_BATCH_WORKFLOW_MAX_AUDIENCE_SIZE` in nodejs/src/cdp/config.ts — the cap the batch
 * consumer enforces by silently truncating the fan-out. We reject past it here so MCP callers get an
 * explicit error instead of an under-the-hood partial run. Keep the two values in sync.
 */
export const BATCH_WORKFLOW_MAX_AUDIENCE_SIZE = 5000

type BlastRadius = { affected: number; total: number }

type WorkflowTrigger = { type?: string; filters?: unknown }

async function fetchWorkflow(
    context: Context,
    projectId: string,
    workflowId: string
): Promise<{ status: string | undefined; trigger: WorkflowTrigger }> {
    const workflow = await context.api.request<{ status?: string; trigger?: unknown }>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(workflowId))}/`,
    })
    return { status: workflow.status, trigger: (workflow.trigger ?? {}) as WorkflowTrigger }
}

function triggerFilters(trigger: WorkflowTrigger): unknown {
    return trigger.filters ?? { properties: [] }
}

async function sizeAudience(context: Context, projectId: string, filters: unknown): Promise<BlastRadius> {
    return await context.api.request<BlastRadius>({
        method: 'POST',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/user_blast_radius/`,
        body: { filters },
    })
}

/**
 * Echo-back guard: the caller must have sized the audience with workflows-blast-radius and surfaced the
 * number to the user. We recompute it here and reject on drift or over-cap before any fan-out.
 */
function assertAcknowledged(affected: number, acknowledged: number): void {
    if (affected !== acknowledged) {
        throw new Error(
            `Audience size is now ${affected} users (you acknowledged ${acknowledged}). Re-check with ` +
                `workflows-blast-radius and confirm the new count with the user before running.`
        )
    }
    if (affected > BATCH_WORKFLOW_MAX_AUDIENCE_SIZE) {
        throw new Error(
            `Audience of ${affected} users exceeds the ${BATCH_WORKFLOW_MAX_AUDIENCE_SIZE}-user cap. Narrow the ` +
                `workflow's batch trigger filters to reduce the audience, then try again.`
        )
    }
}

const BlastRadiusSchema = z.object({
    workflow_id: z.string().describe('ID of the workflow whose batch-trigger audience to size.'),
})

export const workflowsBlastRadius = (): ToolBase<typeof BlastRadiusSchema, BlastRadius> => ({
    name: 'workflows-blast-radius',
    schema: BlastRadiusSchema,
    handler: async (context, params) => {
        const projectId = await context.stateManager.getProjectId()
        const { trigger } = await fetchWorkflow(context, projectId, params.workflow_id)
        return await sizeAudience(context, projectId, triggerFilters(trigger))
    },
})

const RunBatchSchema = z.object({
    workflow_id: z.string().describe('ID of the batch workflow to run now.'),
    acknowledged_affected_count: z
        .number()
        .int()
        .describe(
            'The affected-user count from workflows-blast-radius that you showed the user AND they explicitly ' +
                'confirmed before you called this — never size and fire in one step. Rejected if it no longer ' +
                'matches the current audience, forcing a re-check.'
        ),
    variables: z
        .record(z.string(), z.unknown())
        .optional()
        .describe('Optional {key: value} variable overrides for this run; defaults to the workflow definition.'),
})

export const workflowsRunBatch = (): ToolBase<typeof RunBatchSchema, unknown> => ({
    name: 'workflows-run-batch',
    schema: RunBatchSchema,
    handler: async (context, params) => {
        const projectId = await context.stateManager.getProjectId()
        const { status, trigger } = await fetchWorkflow(context, projectId, params.workflow_id)

        if (trigger.type !== 'batch') {
            throw new Error(
                `workflows-run-batch only applies to workflows with a 'batch' trigger (this one is ` +
                    `'${trigger.type ?? 'unknown'}'). Use workflows-run to test-invoke, or a schedule for recurring runs.`
            )
        }

        if (status !== 'active') {
            throw new Error(
                `Workflow is not active (status '${status ?? 'unknown'}') — a batch run sends real messages, so the ` +
                    `workflow must be enabled first with workflows-enable.`
            )
        }

        const filters = triggerFilters(trigger)
        const { affected } = await sizeAudience(context, projectId, filters)
        assertAcknowledged(affected, params.acknowledged_affected_count)

        return await context.api.request({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.workflow_id))}/batch_jobs/`,
            body: { filters, ...(params.variables !== undefined ? { variables: params.variables } : {}) },
        })
    },
})

const ScheduleCreateSchema = z.object({
    workflow_id: z.string().describe('ID of the batch or schedule workflow to attach the schedule to.'),
    rrule: z
        .string()
        .describe("iCalendar RRULE (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour."),
    starts_at: z.string().describe('ISO 8601 datetime the schedule starts from.'),
    timezone: z.string().optional().describe("IANA timezone for the RRULE (default 'UTC')."),
    acknowledged_affected_count: z
        .number()
        .int()
        .optional()
        .describe(
            'Required for a batch (audience) workflow: the affected-user count from workflows-blast-radius that you ' +
                'showed the user AND they explicitly confirmed before scheduling. Each firing re-broadcasts to the ' +
                "audience at that time; rejected if it no longer matches. Not needed for a 'schedule' trigger " +
                '(person-less — no audience).'
        ),
    variables: z
        .record(z.string(), z.unknown())
        .optional()
        .describe('Optional {key: value} variable overrides merged with the workflow defaults on each run.'),
})

export const workflowsScheduleCreate = (): ToolBase<typeof ScheduleCreateSchema, unknown> => ({
    name: 'workflows-schedule-create',
    schema: ScheduleCreateSchema,
    handler: async (context, params) => {
        const projectId = await context.stateManager.getProjectId()
        const { trigger } = await fetchWorkflow(context, projectId, params.workflow_id)

        if (trigger.type !== 'batch' && trigger.type !== 'schedule') {
            throw new Error(
                `workflows-schedule-create only applies to workflows with a 'batch' or 'schedule' trigger (this one ` +
                    `is '${trigger.type ?? 'unknown'}').`
            )
        }

        // Only a 'batch' trigger has an audience that each firing broadcasts to, so only it needs the
        // blast-radius echo-back. A 'schedule' trigger is person-less — no audience to size or acknowledge.
        if (trigger.type === 'batch') {
            if (params.acknowledged_affected_count === undefined) {
                throw new Error(
                    'acknowledged_affected_count is required for a batch (audience) workflow — size the audience with ' +
                        'workflows-blast-radius and confirm the count with the user first.'
                )
            }
            const { affected } = await sizeAudience(context, projectId, triggerFilters(trigger))
            assertAcknowledged(affected, params.acknowledged_affected_count)
        }

        return await context.api.request({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.workflow_id))}/schedules/`,
            body: {
                rrule: params.rrule,
                starts_at: params.starts_at,
                ...(params.timezone !== undefined ? { timezone: params.timezone } : {}),
                ...(params.variables !== undefined ? { variables: params.variables } : {}),
            },
        })
    },
})
