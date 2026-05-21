/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Upsert a wizard session. The session_id key determines whether this creates a new row or replaces an existing one.
 */
export const wizardSessionsCreateBodySessionIdMax = 255

export const wizardSessionsCreateBodyWorkflowIdMax = 255

export const wizardSessionsCreateBodySkillIdMax = 255

export const WizardSessionsCreateBody = /* @__PURE__ */ zod.object({
    session_id: zod.string().max(wizardSessionsCreateBodySessionIdMax),
    workflow_id: zod.string().max(wizardSessionsCreateBodyWorkflowIdMax),
    skill_id: zod.string().max(wizardSessionsCreateBodySkillIdMax),
    started_at: zod.iso.datetime({ offset: true }),
    run_phase: zod
        .enum(['idle', 'running', 'completed', 'error'])
        .describe('\* `idle` - idle\n\* `running` - running\n\* `completed` - completed\n\* `error` - error'),
    tasks: zod.array(
        zod.object({
            id: zod
                .string()
                .describe('Stable identifier the wizard assigned to this task. Used to track lifecycle across pushes.'),
            title: zod
                .string()
                .describe(
                    "Human-readable title of the task. Should be updated if the task's purpose changes, but can remain the same if only the status changes."
                ),
            status: zod
                .enum(['pending', 'in_progress', 'completed', 'failed', 'canceled'])
                .describe(
                    '\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                )
                .describe(
                    'Current lifecycle stage of the task.\n\n\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                ),
        })
    ),
    event_plan: zod.unknown().optional(),
    error: zod.unknown().optional(),
})

export const wizardSessionsUpdateBodySessionIdMax = 255

export const wizardSessionsUpdateBodyWorkflowIdMax = 255

export const wizardSessionsUpdateBodySkillIdMax = 255

export const WizardSessionsUpdateBody = /* @__PURE__ */ zod.object({
    session_id: zod.string().max(wizardSessionsUpdateBodySessionIdMax),
    workflow_id: zod.string().max(wizardSessionsUpdateBodyWorkflowIdMax),
    skill_id: zod.string().max(wizardSessionsUpdateBodySkillIdMax),
    started_at: zod.iso.datetime({ offset: true }),
    run_phase: zod
        .enum(['idle', 'running', 'completed', 'error'])
        .describe('\* `idle` - idle\n\* `running` - running\n\* `completed` - completed\n\* `error` - error'),
    tasks: zod.array(
        zod.object({
            id: zod
                .string()
                .describe('Stable identifier the wizard assigned to this task. Used to track lifecycle across pushes.'),
            title: zod
                .string()
                .describe(
                    "Human-readable title of the task. Should be updated if the task's purpose changes, but can remain the same if only the status changes."
                ),
            status: zod
                .enum(['pending', 'in_progress', 'completed', 'failed', 'canceled'])
                .describe(
                    '\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                )
                .describe(
                    'Current lifecycle stage of the task.\n\n\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                ),
        })
    ),
    event_plan: zod.unknown().optional(),
    error: zod.unknown().optional(),
})

export const wizardSessionsPartialUpdateBodySessionIdMax = 255

export const wizardSessionsPartialUpdateBodyWorkflowIdMax = 255

export const wizardSessionsPartialUpdateBodySkillIdMax = 255

export const WizardSessionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    session_id: zod.string().max(wizardSessionsPartialUpdateBodySessionIdMax).optional(),
    workflow_id: zod.string().max(wizardSessionsPartialUpdateBodyWorkflowIdMax).optional(),
    skill_id: zod.string().max(wizardSessionsPartialUpdateBodySkillIdMax).optional(),
    started_at: zod.iso.datetime({ offset: true }).optional(),
    run_phase: zod
        .enum(['idle', 'running', 'completed', 'error'])
        .optional()
        .describe('\* `idle` - idle\n\* `running` - running\n\* `completed` - completed\n\* `error` - error'),
    tasks: zod
        .array(
            zod.object({
                id: zod
                    .string()
                    .describe(
                        'Stable identifier the wizard assigned to this task. Used to track lifecycle across pushes.'
                    ),
                title: zod
                    .string()
                    .describe(
                        "Human-readable title of the task. Should be updated if the task's purpose changes, but can remain the same if only the status changes."
                    ),
                status: zod
                    .enum(['pending', 'in_progress', 'completed', 'failed', 'canceled'])
                    .describe(
                        '\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                    )
                    .describe(
                        'Current lifecycle stage of the task.\n\n\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                    ),
            })
        )
        .optional(),
    event_plan: zod.unknown().optional(),
    error: zod.unknown().optional(),
})

/**
 * Upsert a wizard session. The session_id key determines whether this creates a new row or replaces an existing one.
 */
export const wizardCreateBodySessionIdMax = 255

export const wizardCreateBodyWorkflowIdMax = 255

export const wizardCreateBodySkillIdMax = 255

export const WizardCreateBody = /* @__PURE__ */ zod.object({
    session_id: zod.string().max(wizardCreateBodySessionIdMax),
    workflow_id: zod.string().max(wizardCreateBodyWorkflowIdMax),
    skill_id: zod.string().max(wizardCreateBodySkillIdMax),
    started_at: zod.iso.datetime({ offset: true }),
    run_phase: zod
        .enum(['idle', 'running', 'completed', 'error'])
        .describe('\* `idle` - idle\n\* `running` - running\n\* `completed` - completed\n\* `error` - error'),
    tasks: zod.array(
        zod.object({
            id: zod
                .string()
                .describe('Stable identifier the wizard assigned to this task. Used to track lifecycle across pushes.'),
            title: zod
                .string()
                .describe(
                    "Human-readable title of the task. Should be updated if the task's purpose changes, but can remain the same if only the status changes."
                ),
            status: zod
                .enum(['pending', 'in_progress', 'completed', 'failed', 'canceled'])
                .describe(
                    '\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                )
                .describe(
                    'Current lifecycle stage of the task.\n\n\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                ),
        })
    ),
    event_plan: zod.unknown().optional(),
    error: zod.unknown().optional(),
})

export const wizardUpdateBodySessionIdMax = 255

export const wizardUpdateBodyWorkflowIdMax = 255

export const wizardUpdateBodySkillIdMax = 255

export const WizardUpdateBody = /* @__PURE__ */ zod.object({
    session_id: zod.string().max(wizardUpdateBodySessionIdMax),
    workflow_id: zod.string().max(wizardUpdateBodyWorkflowIdMax),
    skill_id: zod.string().max(wizardUpdateBodySkillIdMax),
    started_at: zod.iso.datetime({ offset: true }),
    run_phase: zod
        .enum(['idle', 'running', 'completed', 'error'])
        .describe('\* `idle` - idle\n\* `running` - running\n\* `completed` - completed\n\* `error` - error'),
    tasks: zod.array(
        zod.object({
            id: zod
                .string()
                .describe('Stable identifier the wizard assigned to this task. Used to track lifecycle across pushes.'),
            title: zod
                .string()
                .describe(
                    "Human-readable title of the task. Should be updated if the task's purpose changes, but can remain the same if only the status changes."
                ),
            status: zod
                .enum(['pending', 'in_progress', 'completed', 'failed', 'canceled'])
                .describe(
                    '\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                )
                .describe(
                    'Current lifecycle stage of the task.\n\n\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                ),
        })
    ),
    event_plan: zod.unknown().optional(),
    error: zod.unknown().optional(),
})

export const wizardPartialUpdateBodySessionIdMax = 255

export const wizardPartialUpdateBodyWorkflowIdMax = 255

export const wizardPartialUpdateBodySkillIdMax = 255

export const WizardPartialUpdateBody = /* @__PURE__ */ zod.object({
    session_id: zod.string().max(wizardPartialUpdateBodySessionIdMax).optional(),
    workflow_id: zod.string().max(wizardPartialUpdateBodyWorkflowIdMax).optional(),
    skill_id: zod.string().max(wizardPartialUpdateBodySkillIdMax).optional(),
    started_at: zod.iso.datetime({ offset: true }).optional(),
    run_phase: zod
        .enum(['idle', 'running', 'completed', 'error'])
        .optional()
        .describe('\* `idle` - idle\n\* `running` - running\n\* `completed` - completed\n\* `error` - error'),
    tasks: zod
        .array(
            zod.object({
                id: zod
                    .string()
                    .describe(
                        'Stable identifier the wizard assigned to this task. Used to track lifecycle across pushes.'
                    ),
                title: zod
                    .string()
                    .describe(
                        "Human-readable title of the task. Should be updated if the task's purpose changes, but can remain the same if only the status changes."
                    ),
                status: zod
                    .enum(['pending', 'in_progress', 'completed', 'failed', 'canceled'])
                    .describe(
                        '\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                    )
                    .describe(
                        'Current lifecycle stage of the task.\n\n\* `pending` - pending\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `canceled` - canceled'
                    ),
            })
        )
        .optional(),
    event_plan: zod.unknown().optional(),
    error: zod.unknown().optional(),
})
