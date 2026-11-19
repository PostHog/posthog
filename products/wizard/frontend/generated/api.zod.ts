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
 * Start the setup agent in the cloud on a GitHub repository of this project. It adds PostHog to the code and opens a pull request. Each user can have one setup run active per project at a time.
 * @summary Start a setup run
 */
export const wizardInstallsCreateBodyRepositoryMax = 255

export const wizardInstallsCreateBodyBranchMax = 255

export const wizardInstallsCreateBodyIdempotencyKeyMax = 255

export const WizardInstallsCreateBody = /* @__PURE__ */ zod.object({
    repository: zod
        .string()
        .max(wizardInstallsCreateBodyRepositoryMax)
        .describe(
            "GitHub repository to set up, in owner\/name format. The project's GitHub connection must have access to it."
        ),
    branch: zod
        .string()
        .max(wizardInstallsCreateBodyBranchMax)
        .optional()
        .describe(
            "Branch to start from and to open the pull request against. Defaults to the repository's default branch."
        ),
    idempotency_key: zod
        .string()
        .max(wizardInstallsCreateBodyIdempotencyKeyMax)
        .optional()
        .describe(
            'Unique key for this request. A retry with the same key returns the same run instead of starting another.'
        ),
})

/**
 * Create a local or cloud Wizard run for a project workspace.
 */
export const wizardRunsCreateBodyProgramIdRegExp = new RegExp('^[a-z0-9]+(?:-[a-z0-9]+)\*$')
export const wizardRunsCreateBodyWorkspaceOneOneProjectNameMax = 255

export const wizardRunsCreateBodyWorkspaceOneTwoRepositoryMax = 255

export const wizardRunsCreateBodyIdempotencyKeyMax = 255

export const WizardRunsCreateBody = /* @__PURE__ */ zod.object({
    program_id: zod.string().regex(wizardRunsCreateBodyProgramIdRegExp).describe('Registry program to run.'),
    environment: zod
        .enum(['local', 'cloud'])
        .describe('\* `local` - local\n\* `cloud` - cloud')
        .describe('Where the setup agent runs.\n\n\* `local` - local\n\* `cloud` - cloud'),
    workspace: zod
        .union([
            zod.object({
                type: zod.enum(['local_folder']).describe("Selects a folder on the user's machine as the workspace."),
                project_name: zod
                    .string()
                    .max(wizardRunsCreateBodyWorkspaceOneOneProjectNameMax)
                    .describe('Name of the project in the local folder.'),
            }),
            zod.object({
                type: zod.enum(['git_repository']).describe('Selects a GitHub repository as the workspace.'),
                repository: zod
                    .string()
                    .max(wizardRunsCreateBodyWorkspaceOneTwoRepositoryMax)
                    .describe('GitHub repository in owner\/name format.'),
            }),
        ])
        .describe('Project that the setup agent works on.'),
    idempotency_key: zod
        .string()
        .max(wizardRunsCreateBodyIdempotencyKeyMax)
        .optional()
        .describe('Unique key that makes cloud run creation safe to retry.'),
    wizard_version: zod
        .string()
        .optional()
        .describe('Wizard package version to run. Defaults to the backend pin and accepts latest explicitly.'),
})

/**
 * Change the terminal status of a local Wizard run.
 */
export const wizardRunsPartialUpdateBodyErrorCodeMax = 50

export const WizardRunsPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['completed', 'failed', 'cancelled'])
        .describe('\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled')
        .optional()
        .describe(
            'New terminal status for the Wizard run.\n\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
        ),
    error_code: zod
        .string()
        .max(wizardRunsPartialUpdateBodyErrorCodeMax)
        .nullish()
        .describe('Machine-readable reason the Wizard run failed.'),
})

/**
 * API endpoints for managing Wizard run tasks. Access is scoped to the Wizard only.
 *
 * The Wizard should be the only client that can update the tasks of a run.
 */
export const wizardRunsTasksUpdateBodyTasksItemNameMax = 255

export const WizardRunsTasksUpdateBody = /* @__PURE__ */ zod.object({
    tasks: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(wizardRunsTasksUpdateBodyTasksItemNameMax)
                    .describe('Task name, unique within this run and stable across snapshots.'),
                status: zod
                    .enum(['created', 'running', 'completed', 'failed'])
                    .describe(
                        '\* `created` - created\n\* `running` - running\n\* `completed` - completed\n\* `failed` - failed'
                    )
                    .describe(
                        'Current task status reported by the setup agent.\n\n\* `created` - created\n\* `running` - running\n\* `completed` - completed\n\* `failed` - failed'
                    ),
            })
        )
        .describe("Complete task snapshot. An empty list clears the run's tasks."),
})

/**
 * @summary Record the tools a wizard scan found in a codebase
 */
export const wizardScansCreateBodySessionIdMax = 255

export const wizardScansCreateBodyProgramMax = 50

export const wizardScansCreateBodyWizardVersionMax = 32

export const wizardScansCreateBodyWorkspaceFingerprintMax = 64

export const wizardScansCreateBodyWorkspaceFingerprintRegExp = new RegExp('^[0-9a-f]{64}$')
export const wizardScansCreateBodyToolsItemKindMax = 64

export const wizardScansCreateBodyToolsItemSignalsItemSourceMax = 32

export const wizardScansCreateBodyToolsItemSignalsItemNameMax = 255

export const wizardScansCreateBodyToolsItemSignalsItemFileMax = 512

export const wizardScansCreateBodyToolsItemSignalsMax = 50

export const wizardScansCreateBodyToolsMax = 300

export const wizardScansCreateBodyCompleteDefault = true

export const WizardScansCreateBody = /* @__PURE__ */ zod.object({
    session_id: zod.string().max(wizardScansCreateBodySessionIdMax).describe('The wizard run that made the scan.'),
    program: zod
        .string()
        .max(wizardScansCreateBodyProgramMax)
        .describe('The wizard program that scanned, such as `posthog-integration` or `warehouse-source`.'),
    wizard_version: zod
        .string()
        .max(wizardScansCreateBodyWizardVersionMax)
        .describe('Version of the wizard that made the scan.'),
    workspace_fingerprint: zod
        .string()
        .max(wizardScansCreateBodyWorkspaceFingerprintMax)
        .regex(wizardScansCreateBodyWorkspaceFingerprintRegExp)
        .describe('sha256 hex digest that identifies the scanned repository without naming it.'),
    scanned_at: zod.iso.datetime({ offset: true }).describe('When the wizard scanned the codebase.'),
    tools: zod
        .array(
            zod.object({
                kind: zod
                    .string()
                    .max(wizardScansCreateBodyToolsItemKindMax)
                    .describe("The tool's kind in the wizard tool catalog, such as `Stripe` or `Amplitude`."),
                signals: zod
                    .array(
                        zod.object({
                            source: zod
                                .string()
                                .max(wizardScansCreateBodyToolsItemSignalsItemSourceMax)
                                .describe(
                                    'Where the wizard found the tool, such as `npm`, `pypi`, `env_key` or `script_host`.'
                                ),
                            name: zod
                                .string()
                                .max(wizardScansCreateBodyToolsItemSignalsItemNameMax)
                                .describe(
                                    'The package name, `.env` key name or script host that matched. Never a `.env` value.'
                                ),
                            file: zod
                                .string()
                                .max(wizardScansCreateBodyToolsItemSignalsItemFileMax)
                                .nullish()
                                .describe('Path of the file the signal came from, relative to the scanned directory.'),
                        })
                    )
                    .max(wizardScansCreateBodyToolsItemSignalsMax)
                    .describe('The signals that matched this tool.'),
            })
        )
        .max(wizardScansCreateBodyToolsMax)
        .describe('Every tool the scan found. An empty list is a scan that found nothing.'),
    complete: zod
        .boolean()
        .default(wizardScansCreateBodyCompleteDefault)
        .describe('False when the scan could not read the whole workspace. Tools it did not find are then kept.'),
})

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
