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
 * Upsert a wizard session. The `session_id` key is the idempotency anchor — reposting the same `session_id` replaces the existing row. Returns 201 on create, 200 on update.
 */
export const wizardSessionsCreateBodySessionIdMax = 255

export const wizardSessionsCreateBodyWorkflowIdMax = 255

export const wizardSessionsCreateBodySkillIdMax = 255

export const WizardSessionsCreateBody = /* @__PURE__ */ zod
    .object({
        session_id: zod
            .string()
            .max(wizardSessionsCreateBodySessionIdMax)
            .describe(
                "Stable identifier the wizard mints for this run (format: '{workflow_id}-{skill_id}-{started_at_iso}'). Reposting with the same session_id upserts the existing row."
            ),
        workflow_id: zod
            .string()
            .max(wizardSessionsCreateBodyWorkflowIdMax)
            .describe("High-level workflow being run, e.g. 'onboarding', 'migration', 'audit'."),
        skill_id: zod
            .string()
            .max(wizardSessionsCreateBodySkillIdMax)
            .describe("Specific skill within the workflow, e.g. 'nextjs', 'django', 'laravel'."),
        started_at: zod.iso
            .datetime({ offset: true })
            .describe('UTC timestamp when the wizard started this run. Matches the timestamp encoded in session_id.'),
        run_phase: zod
            .enum(['idle', 'running', 'completed', 'error'])
            .describe('\* `idle` - IDLE\n\* `running` - RUNNING\n\* `completed` - COMPLETED\n\* `error` - ERROR')
            .describe(
                'Lifecycle stage of the wizard run.\n\n\* `idle` - IDLE\n\* `running` - RUNNING\n\* `completed` - COMPLETED\n\* `error` - ERROR'
            ),
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
        event_plan: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'Optional structured plan of events the wizard intends to instrument. Schema is workflow-specific.'
            ),
        error: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe("Populated when run_phase='error'. Shape: { type: string, message: string }."),
    })
    .describe('Input: validates the JSON the wizard CLI posts. team_id is derived from URL.')

/**
 * Submit a local wizard audit's check ledger for the post-onboarding setup review. The signals pipeline turns the strongest failing checks into a handful of complimentary implementation PRs in the inbox. This should only be called by the PostHog Wizard. Fire-and-forget: always 202 once the payload validates — the review itself is idempotent (one per team, ever) and gated server-side on org AI consent.
 */
export const wizardSessionsSetupReviewCreateBodyRepositoryMax = 300

export const wizardSessionsSetupReviewCreateBodyChecksItemIdMax = 200

export const wizardSessionsSetupReviewCreateBodyChecksItemLabelMax = 500

export const wizardSessionsSetupReviewCreateBodyChecksItemStatusMax = 50

export const wizardSessionsSetupReviewCreateBodyChecksItemAreaMax = 200

export const wizardSessionsSetupReviewCreateBodyChecksItemFileMax = 1000

export const WizardSessionsSetupReviewCreateBody = /* @__PURE__ */ zod
    .object({
        repository: zod
            .string()
            .max(wizardSessionsSetupReviewCreateBodyRepositoryMax)
            .describe(
                "GitHub repository the audited project lives in, as 'owner\/repo'. The signals pipeline uses it to pick the implementation repo for the review's PRs."
            ),
        checks: zod.array(
            zod
                .object({
                    id: zod.string().max(wizardSessionsSetupReviewCreateBodyChecksItemIdMax),
                    label: zod.string().max(wizardSessionsSetupReviewCreateBodyChecksItemLabelMax),
                    status: zod.string().max(wizardSessionsSetupReviewCreateBodyChecksItemStatusMax),
                    area: zod.string().max(wizardSessionsSetupReviewCreateBodyChecksItemAreaMax).nullish(),
                    file: zod.string().max(wizardSessionsSetupReviewCreateBodyChecksItemFileMax).nullish(),
                    details: zod.string().nullish(),
                })
                .describe("One row of the wizard audit's check ledger (.posthog-audit-checks.json).")
        ),
    })
    .describe("Input: a local wizard audit's check ledger, posted for the signals setup review.")
