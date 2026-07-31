/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const pendingInputApiIdMax = 255

export const pendingInputApiQuestionCountMax = 100

export const pendingInputApiSensitiveDefault = false
export const pendingInputApiPromptsItemMax = 2000

export const pendingInputApiPromptsMax = 10

export const PendingInputApi = zod
    .object({
        id: zod
            .string()
            .max(pendingInputApiIdMax)
            .describe('Identifier the wizard mints for this question. Changes when a new question is asked.'),
        asked_at: zod.iso
            .datetime({ offset: true })
            .optional()
            .describe("UTC timestamp when the wizard asked. Defaults to the session's update time when absent."),
        question_count: zod
            .number()
            .min(1)
            .max(pendingInputApiQuestionCountMax)
            .optional()
            .describe('How many questions this single ask covers.'),
        sensitive: zod
            .boolean()
            .default(pendingInputApiSensitiveDefault)
            .describe('Whether the answer is a secret. Sensitive questions never carry prompt text.'),
        prompts: zod
            .array(zod.string().max(pendingInputApiPromptsItemMax))
            .max(pendingInputApiPromptsMax)
            .optional()
            .describe('The question text shown to the user. Always empty for sensitive questions.'),
    })
    .describe(
        'The in-flight `wizard_ask` question. Typed rather than a free-form dict so the shape the\nwidget renders is enforced at the edge instead of trusted from the producer.'
    )

export type PendingInputApi = zod.input<typeof PendingInputApi>
export type PendingInputApiOutput = zod.output<typeof PendingInputApi>

export const RunPhaseEnumApi = zod
    .enum(['idle', 'running', 'completed', 'error'])
    .describe('\* `idle` - IDLE\n\* `running` - RUNNING\n\* `completed` - COMPLETED\n\* `error` - ERROR')

export type RunPhaseEnumApi = zod.input<typeof RunPhaseEnumApi>
export type RunPhaseEnumApiOutput = zod.output<typeof RunPhaseEnumApi>

export const WizardTaskDTOStatusEnumApi = zod
    .enum(['pending', 'in_progress', 'completed', 'failed', 'canceled'])
    .describe(
        '\* `pending` - PENDING\n\* `in_progress` - IN_PROGRESS\n\* `completed` - COMPLETED\n\* `failed` - FAILED\n\* `canceled` - CANCELED'
    )

export type WizardTaskDTOStatusEnumApi = zod.input<typeof WizardTaskDTOStatusEnumApi>
export type WizardTaskDTOStatusEnumApiOutput = zod.output<typeof WizardTaskDTOStatusEnumApi>

export const WizardTaskDTOApi = zod.object({
    id: zod.string(),
    title: zod.string(),
    status: WizardTaskDTOStatusEnumApi,
})

export type WizardTaskDTOApi = zod.input<typeof WizardTaskDTOApi>
export type WizardTaskDTOApiOutput = zod.output<typeof WizardTaskDTOApi>

export const WizardSessionUserDTOApi = zod.object({
    id: zod.number(),
    first_name: zod.string(),
    email: zod.string(),
})

export type WizardSessionUserDTOApi = zod.input<typeof WizardSessionUserDTOApi>
export type WizardSessionUserDTOApiOutput = zod.output<typeof WizardSessionUserDTOApi>

export const WizardSessionDTOApi = zod
    .object({
        pending_input: zod
            .union([PendingInputApi, zod.null()])
            .describe('The question the wizard is currently blocked on, or null when nothing is pending.'),
        session_id: zod.string(),
        team_id: zod.number(),
        workflow_id: zod.string(),
        skill_id: zod.string(),
        started_at: zod.iso.datetime({ offset: true }),
        run_phase: RunPhaseEnumApi,
        tasks: zod.array(WizardTaskDTOApi),
        event_plan: zod.record(zod.string(), zod.unknown()).nullable(),
        error: zod.record(zod.string(), zod.unknown()).nullable(),
        created_by: zod
            .union([WizardSessionUserDTOApi, zod.null()])
            .describe(
                'The user who initiated this wizard run (null for runs created before attribution existed). Lets the UI name whose run it is.'
            ),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        is_stale: zod.boolean(),
    })
    .describe('Output: serialises a WizardSessionDTO returned by the facade.')

export type WizardSessionDTOApi = zod.input<typeof WizardSessionDTOApi>
export type WizardSessionDTOApiOutput = zod.output<typeof WizardSessionDTOApi>

export const PaginatedWizardSessionDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(WizardSessionDTOApi),
})

export type PaginatedWizardSessionDTOListApi = zod.input<typeof PaginatedWizardSessionDTOListApi>
export type PaginatedWizardSessionDTOListApiOutput = zod.output<typeof PaginatedWizardSessionDTOListApi>

export const upsertWizardSessionRequestApiSessionIdMax = 255

export const upsertWizardSessionRequestApiWorkflowIdMax = 255

export const upsertWizardSessionRequestApiSkillIdMax = 255

export const UpsertWizardSessionRequestApi = zod
    .object({
        pending_input: zod
            .union([PendingInputApi, zod.null()])
            .optional()
            .describe(
                'Populated while the wizard is blocked on a question in the terminal. Null\/absent means no input is pending; a push without it clears the previous prompt.'
            ),
        session_id: zod
            .string()
            .max(upsertWizardSessionRequestApiSessionIdMax)
            .describe(
                "Stable identifier the wizard mints for this run (format: '{workflow_id}-{skill_id}-{started_at_iso}'). Reposting with the same session_id upserts the existing row."
            ),
        workflow_id: zod
            .string()
            .max(upsertWizardSessionRequestApiWorkflowIdMax)
            .describe("High-level workflow being run, e.g. 'onboarding', 'migration', 'audit'."),
        skill_id: zod
            .string()
            .max(upsertWizardSessionRequestApiSkillIdMax)
            .describe("Specific skill within the workflow, e.g. 'nextjs', 'django', 'laravel'."),
        started_at: zod.iso
            .datetime({ offset: true })
            .describe('UTC timestamp when the wizard started this run. Matches the timestamp encoded in session_id.'),
        run_phase: RunPhaseEnumApi.describe(
            'Lifecycle stage of the wizard run.\n\n\* `idle` - IDLE\n\* `running` - RUNNING\n\* `completed` - COMPLETED\n\* `error` - ERROR'
        ),
        tasks: zod.array(WizardTaskDTOApi),
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

export type UpsertWizardSessionRequestApi = zod.input<typeof UpsertWizardSessionRequestApi>
export type UpsertWizardSessionRequestApiOutput = zod.output<typeof UpsertWizardSessionRequestApi>
