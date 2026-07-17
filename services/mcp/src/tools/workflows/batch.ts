import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

type BlastRadius = { affected: number; total: number; limit: number }

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
 * number to the user. We recompute it here and reject on drift or over-cap before any fan-out. The cap is
 * the per-team `limit` the blast-radius endpoint returns (HOGFLOW_BATCH_TRIGGER_LIMIT), which the batch
 * consumer also enforces — so the run is rejected here rather than silently truncated downstream.
 */
function assertAcknowledged(affected: number, acknowledged: number, limit: number): void {
    if (affected !== acknowledged) {
        throw new Error(
            `Audience size is now ${affected} users (you acknowledged ${acknowledged}). Re-check with ` +
                `workflows-blast-radius and confirm the new count with the user before running.`
        )
    }
    if (affected > limit) {
        throw new Error(
            `Audience of ${affected} users exceeds the ${limit}-user cap for this project. Narrow the ` +
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
                    `'${trigger.type ?? 'unknown'}'). Use workflows-test-run to test-invoke, or a schedule for recurring runs.`
            )
        }

        if (status !== 'active') {
            throw new Error(
                `Workflow is not active (status '${status ?? 'unknown'}') — a batch run sends real messages, so the ` +
                    `workflow must be enabled first with workflows-enable.`
            )
        }

        const filters = triggerFilters(trigger)
        const { affected, limit } = await sizeAudience(context, projectId, filters)
        assertAcknowledged(affected, params.acknowledged_affected_count, limit)

        return await context.api.request({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/hog_flows/${encodeURIComponent(String(params.workflow_id))}/batch_jobs/`,
            body: { filters, ...(params.variables !== undefined ? { variables: params.variables } : {}) },
        })
    },
})

const ScheduleCreateSchema = z.object({
    workflow_id: z.string().describe('ID of the batch workflow to attach the recurring schedule to.'),
    rrule: z
        .string()
        .describe("iCalendar RRULE (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour."),
    starts_at: z.string().describe('ISO 8601 datetime the schedule starts from.'),
    timezone: z.string().optional().describe("IANA timezone for the RRULE (default 'UTC')."),
    acknowledged_affected_count: z
        .number()
        .int()
        .describe(
            'The affected-user count from workflows-blast-radius that you showed the user AND they explicitly ' +
                'confirmed before scheduling. Each firing re-broadcasts to the audience at that time; rejected if it ' +
                'no longer matches.'
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
        const { status, trigger } = await fetchWorkflow(context, projectId, params.workflow_id)

        if (trigger.type !== 'batch') {
            throw new Error(
                `workflows-schedule-create only applies to workflows with a 'batch' trigger (this one is ` +
                    `'${trigger.type ?? 'unknown'}').`
            )
        }

        // Require the workflow to be active before scheduling. A draft's trigger can still be edited, so
        // scheduling a draft would let the audience be broadened after you acknowledged it (the scheduler
        // uses the trigger's filters at fire time). An active workflow's trigger can't be edited via MCP,
        // so the acknowledged audience is locked in.
        if (status !== 'active') {
            throw new Error(
                `Workflow is not active (status '${status ?? 'unknown'}') — enable it with workflows-enable before ` +
                    `scheduling. Scheduling a draft would let the audience change after you sized it.`
            )
        }

        const { affected, limit } = await sizeAudience(context, projectId, triggerFilters(trigger))
        assertAcknowledged(affected, params.acknowledged_affected_count, limit)

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
