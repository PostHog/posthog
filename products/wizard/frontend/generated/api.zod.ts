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
 * Upsert a repository detection. The `(repository, kind)` pair is the idempotency anchor — reposting the same pair replaces the existing row. Returns 201 on create, 200 on update.
 */
export const wizardRepositoryDetectionsCreateBodyReportOneProjectsItemPathMax = 512

export const wizardRepositoryDetectionsCreateBodyReportOneProjectsItemFrameworkMax = 100

export const wizardRepositoryDetectionsCreateBodyReportOneProjectsItemVariantMax = 64

export const wizardRepositoryDetectionsCreateBodyReportOneProjectsItemReasonMax = 300

export const wizardRepositoryDetectionsCreateBodyErrorOneTypeMax = 100

export const wizardRepositoryDetectionsCreateBodyErrorOneMessageMax = 2000

export const wizardRepositoryDetectionsCreateBodyRepositoryMax = 255

export const wizardRepositoryDetectionsCreateBodyKindMax = 64

export const WizardRepositoryDetectionsCreateBody = /* @__PURE__ */ zod
    .object({
        report: zod
            .union([
                zod
                    .object({
                        repo_type: zod
                            .enum(['monorepo', 'single'])
                            .describe('\* `monorepo` - monorepo\n\* `single` - single')
                            .describe(
                                'Whether the repository is a multi-project workspace or a single project.\n\n\* `monorepo` - monorepo\n\* `single` - single'
                            ),
                        projects: zod
                            .array(
                                zod
                                    .object({
                                        path: zod
                                            .string()
                                            .max(wizardRepositoryDetectionsCreateBodyReportOneProjectsItemPathMax)
                                            .describe(
                                                "Repo-relative path of the project ('.' for the repository root)."
                                            ),
                                        framework: zod
                                            .string()
                                            .max(wizardRepositoryDetectionsCreateBodyReportOneProjectsItemFrameworkMax)
                                            .describe(
                                                "Human-readable framework name the agent classified, e.g. 'Next.js'."
                                            ),
                                        variant: zod
                                            .string()
                                            .max(wizardRepositoryDetectionsCreateBodyReportOneProjectsItemVariantMax)
                                            .nullish()
                                            .describe(
                                                "Detection-kind-specific target the project matched (e.g. the source-map skill variant 'nextjs'), or null when the stack isn't supported."
                                            ),
                                        has_posthog: zod
                                            .boolean()
                                            .describe('Whether a PostHog SDK is already installed in this project.'),
                                        instrumentable: zod
                                            .boolean()
                                            .describe(
                                                'Whether the detection kind can act on this project (supported variant + SDK present).'
                                            ),
                                        reason: zod
                                            .string()
                                            .max(wizardRepositoryDetectionsCreateBodyReportOneProjectsItemReasonMax)
                                            .nullish()
                                            .describe(
                                                "Why the project is not instrumentable, when it isn't. Human-readable."
                                            ),
                                    })
                                    .describe('One project the detection agent found in the repository.')
                            )
                            .describe('Projects found in the repository, one entry per project manifest.'),
                    })
                    .describe(
                        'The structured result of one detection run. Typed rather than a free-form dict so the\nshape the app renders is enforced at the edge instead of trusted from the producer.'
                    ),
                zod.null(),
            ])
            .optional()
            .describe('The detection result. Exactly one of `report` \/ `error` must be set.'),
        error: zod
            .union([
                zod
                    .object({
                        type: zod
                            .string()
                            .max(wizardRepositoryDetectionsCreateBodyErrorOneTypeMax)
                            .nullish()
                            .describe("Machine-readable failure category, e.g. 'no-manifests', 'agent-error'."),
                        message: zod
                            .string()
                            .max(wizardRepositoryDetectionsCreateBodyErrorOneMessageMax)
                            .describe('Human-readable failure description.'),
                    })
                    .describe('Why a detection run failed. Populated instead of `report`.'),
                zod.null(),
            ])
            .optional()
            .describe('Why the run failed. Exactly one of `report` \/ `error` must be set.'),
        task_run_id: zod
            .uuid()
            .nullish()
            .describe('TaskRun UUID of the cloud run producing this result. Omit for local runs.'),
        repository: zod
            .string()
            .max(wizardRepositoryDetectionsCreateBodyRepositoryMax)
            .describe(
                "Repository the detection ran against, in 'org\/repo' form. Together with `kind` this is the idempotency anchor — reposting the same pair replaces the existing row."
            ),
        kind: zod
            .string()
            .max(wizardRepositoryDetectionsCreateBodyKindMax)
            .describe("Detection flavor, e.g. 'error-tracking-source-maps'."),
    })
    .describe('Input: validates the JSON a detection agent posts. team_id is derived from URL.')

/**
 * Upsert a wizard session. The `session_id` key is the idempotency anchor — reposting the same `session_id` replaces the existing row. Returns 201 on create, 200 on update.
 */
export const wizardSessionsCreateBodyPendingInputOneIdMax = 255

export const wizardSessionsCreateBodyPendingInputOneQuestionCountMax = 100

export const wizardSessionsCreateBodyPendingInputOneSensitiveDefault = false
export const wizardSessionsCreateBodyPendingInputOnePromptsItemMax = 2000

export const wizardSessionsCreateBodyPendingInputOnePromptsMax = 10

export const wizardSessionsCreateBodyHandoffTextMax = 65536

export const wizardSessionsCreateBodySessionIdMax = 255

export const wizardSessionsCreateBodyWorkflowIdMax = 255

export const wizardSessionsCreateBodySkillIdMax = 255

export const WizardSessionsCreateBody = /* @__PURE__ */ zod
    .object({
        pending_input: zod
            .union([
                zod
                    .object({
                        id: zod
                            .string()
                            .max(wizardSessionsCreateBodyPendingInputOneIdMax)
                            .describe(
                                'Identifier the wizard mints for this question. Changes when a new question is asked.'
                            ),
                        asked_at: zod.iso
                            .datetime({ offset: true })
                            .optional()
                            .describe(
                                "UTC timestamp when the wizard asked. Defaults to the session's update time when absent."
                            ),
                        question_count: zod
                            .number()
                            .min(1)
                            .max(wizardSessionsCreateBodyPendingInputOneQuestionCountMax)
                            .optional()
                            .describe('How many questions this single ask covers.'),
                        sensitive: zod
                            .boolean()
                            .default(wizardSessionsCreateBodyPendingInputOneSensitiveDefault)
                            .describe('Whether the answer is a secret. Sensitive questions never carry prompt text.'),
                        prompts: zod
                            .array(zod.string().max(wizardSessionsCreateBodyPendingInputOnePromptsItemMax))
                            .max(wizardSessionsCreateBodyPendingInputOnePromptsMax)
                            .optional()
                            .describe('The question text shown to the user. Always empty for sensitive questions.'),
                    })
                    .describe(
                        'The in-flight `wizard_ask` question. Typed rather than a free-form dict so the shape the\nwidget renders is enforced at the edge instead of trusted from the producer.'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Populated while the wizard is blocked on a question in the terminal. Null\/absent means no input is pending; a push without it clears the previous prompt.'
            ),
        handoff_text: zod
            .string()
            .max(wizardSessionsCreateBodyHandoffTextMax)
            .nullish()
            .describe(
                "Markdown handoff doc for the run (the wizard's setup report). Send it once the run has produced one; omitting it on later pushes keeps the stored value."
            ),
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
