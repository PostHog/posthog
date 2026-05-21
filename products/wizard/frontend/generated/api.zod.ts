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
 * Upsert a wizard session. The session_id key determines whether this creates a new row or replaces an existing one. Always returns 201.
 */
export const WizardSessionsCreateBody = /* @__PURE__ */ zod
    .object({
        session_id: zod.string(),
        workflow_id: zod.string(),
        skill_id: zod.string(),
        started_at: zod.iso.datetime({ offset: true }),
        run_phase: zod
            .enum(['idle', 'running', 'completed', 'error'])
            .describe('\* `idle` - IDLE\n\* `running` - RUNNING\n\* `completed` - COMPLETED\n\* `error` - ERROR'),
        tasks: zod.array(
            zod.object({
                id: zod.string(),
                title: zod.string(),
                status: zod
                    .enum(['pending', 'in_progress', 'completed', 'failed', 'canceled'])
                    .describe(
                        '\* `pending` - PENDING\n\* `in_progress` - IN_PROGRESS\n\* `completed` - COMPLETED\n\* `failed` - FAILED\n\* `canceled` - CANCELED'
                    ),
            })
        ),
        event_plan: zod.record(zod.string(), zod.unknown()).nullish(),
        error: zod.record(zod.string(), zod.unknown()).nullish(),
    })
    .describe('Input: validates the JSON the wizard CLI posts. team_id is derived from URL.')
