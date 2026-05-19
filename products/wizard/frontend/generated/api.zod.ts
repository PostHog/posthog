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
export const WizardSessionsCreateBody = /* @__PURE__ */ zod.object({
    session_id: zod
        .string()
        .describe(
            "Stable identifier the wizard assigns to a run, formatted '{workflow_id}-{skill_id}-{started_at_iso}'. Re-posting with the same session_id upserts the existing row."
        ),
    workflow_id: zod.string().describe("High-level workflow being run, e.g. 'onboarding', 'migration', 'audit'."),
    skill_id: zod
        .string()
        .describe("Specific skill within the workflow, e.g. 'posthog_integration', 'revenue_analytics_setup'."),
    started_at: zod.iso
        .datetime({ offset: true })
        .describe('UTC timestamp when the wizard started this run. Matches the timestamp encoded in session_id.'),
    run_phase: zod
        .enum(['idle', 'running', 'completed', 'error'])
        .describe('\* `idle` - idle\n\* `running` - running\n\* `completed` - completed\n\* `error` - error')
        .describe(
            'Lifecycle stage of the wizard run.\n\n\* `idle` - idle\n\* `running` - running\n\* `completed` - completed\n\* `error` - error'
        ),
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
        .describe(
            "Full snapshot of the wizard's current task list. Each push overwrites the previous list; tasks may be added, removed, or re-ordered between pushes."
        ),
    event_plan: zod
        .unknown()
        .optional()
        .describe('Optional structured plan of events the wizard intends to instrument. Schema is workflow-specific.'),
    error: zod
        .unknown()
        .optional()
        .describe("Populated when run_phase='error'. Shape: { type: string, message: string }."),
})
