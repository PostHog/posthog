import type { ExitCondition, TriggerAuthoringConfig, WorkflowStatus, WorkflowVariable } from './definition.js'
import { compile, type EmitOptions, type EmitResult } from './emit.js'
import type { Path } from './steps.js'

/** The options `workflow` takes. */
export interface WorkflowOptions {
    /**
     * The workflow's identity in the source file, unique for each team.
     *
     * A push resolves the key to a workflow and then creates or updates, so one file
     * reaches a staging project and a production project. PostHog's own id never
     * travels back into the source. Pick a slug an author will recognise, using
     * letters, digits, hyphens and underscores. Renaming a key orphans the old
     * workflow and creates a new one, so treat the key as fixed once it is pushed.
     *
     * The PostHog API accepts `key` from a later backend change on.
     */
    readonly key: string
    /** The name PostHog shows. Free to change, because the identity is the key. */
    readonly name: string
    /** What the workflow is for. Emitted as an empty string when omitted. */
    readonly description?: string
    /**
     * Whether the workflow runs. Omit it to let PostHog own the status. A new workflow
     * starts as a draft because that is the PostHog model default. Set `active` or
     * `draft` in the file only when the file must control the status.
     */
    readonly status?: WorkflowStatus
    /** When a person leaves early. Defaults to `exit_only_at_end`. */
    readonly exitCondition?: ExitCondition
    /**
     * Variables and their defaults. Keys are unique, every default is a string, and the
     * whole list is capped at 5120 bytes. See `WorkflowVariable`.
     */
    readonly variables?: readonly WorkflowVariable[]
    /** What starts a run. Build it with `onEvent`, `onSchedule` or `trigger`. */
    readonly on: TriggerAuthoringConfig
    /** The steps, in order. Build the path with `path`. */
    readonly steps: Path
    /** The terminal step. `reason` is the label PostHog records when a run finishes. */
    readonly exit: { readonly reason: string; readonly name?: string; readonly description?: string }
}

/** One declared workflow, ready to emit. */
export interface Workflow {
    /** The key this workflow was declared with. */
    readonly key: string
    /**
     * Resolves every secret, checks every rule, and returns the definition to push.
     *
     * Call it to see exactly what a push will send. It reads nothing but the file and
     * the environment, so the same file and environment always give the same bytes.
     *
     * @param options - Where to read a `secret` from. Defaults to `process.env`.
     * @returns The definition, and the secret inputs it resolved.
     * @throws {WorkflowError} The first rule the workflow breaks, as a refusal carrying
     * `status`, `message`, `why` and `fix`. The statuses are `duplicate_action_id`,
     * `reserved_action_id`, `invalid_action_id`, `action_id_too_long`,
     * `unnamed_action_id`, `step_name_too_long`, `invalid_key`, `invalid_duration`,
     * `duration_over_unit_cap`, `empty_path`, `invalid_email_sender`,
     * `invalid_sender_address`, `missing_secret`, `nested_secret`, `duplicate_variable_key`
     * and `variables_too_large`.
     */
    emit(options?: EmitOptions): EmitResult
}

/**
 * Declares one workflow, and returns it ready to emit as a definition.
 *
 * A **definition** is the JSON body a push sends to the PostHog API: a list of actions
 * and the edges between them. This function is the only place a definition comes from,
 * and `emit` is what produces it.
 *
 * The compiler decides everything an author would otherwise keep in step:
 *
 * - An **action id** is the slug of the step name, so inserting or reordering a step
 *   leaves every other id alone. PostHog moves in-flight runs between steps by matching
 *   the action id as a string, so a stable id keeps a live run on the step it is on.
 *   Two different steps that take one id are a refusal. Pass `id` on a step to pin an id
 *   through a rename.
 * - The trigger action and the exit action always use the ids `trigger_node` and
 *   `exit_node`.
 * - Edges come from placement, including each branch arm's index.
 * - The definition includes `status` only when the file sets it. PostHog owns the
 *   status otherwise, and a new workflow starts as a draft.
 *
 * Export every workflow the file declares, because the CLI pushes what the file exports
 * and skips the rest. The export name is yours; the identity is the key. Nothing here
 * talks to PostHog: the CLI loads the file, calls `emit`, and pushes the definition.
 *
 * @param options - The workflow's identity, trigger, steps and exit.
 * @returns A workflow whose `emit` produces the definition.
 * @throws {WorkflowError} From `emit`, not from this call. See `Workflow.emit` for the
 * statuses.
 * @example
 * ```ts
 * import { branch, delay, email, onEvent, path, person, secret, webhook, workflow } from '@posthog/workflows'
 *
 * const notifyCrm = webhook({
 *     name: 'Tell the CRM to follow up',
 *     url: 'https://example.com/hooks/onboarding',
 *     body: { distinct_id: '{event.distinct_id}' },
 *     signingSecret: secret('CRM_WEBHOOK_SECRET'),
 * })
 *
 * const welcome = email({
 *     name: 'Welcome the paid customer',
 *     to: '{person.properties.email}',
 *     subject: 'Welcome aboard',
 *     text: 'Thanks for upgrading.',
 *     html: '<p>Thanks for upgrading.</p>',
 * })
 *
 * // Replace this key with your own before you push.
 * export const onboarding = workflow({
 *     key: 'replace-me-onboarding-nudge',
 *     name: 'Onboarding nudge',
 *     variables: [{ key: 'docs_url', type: 'string', default: 'https://example.com/docs' }],
 *     on: onEvent({ event: 'user signed up' }),
 *     steps: path(
 *         delay('1d', { name: 'Wait a day' }),
 *         branch({
 *             name: 'Which plan?',
 *             branches: [
 *                 {
 *                     name: 'Paid plan',
 *                     when: [person('plan', 'exact', ['pro'])],
 *                     then: path(welcome, notifyCrm),
 *                 },
 *                 {
 *                     name: 'Free plan',
 *                     when: [person('plan', 'exact', ['free'])],
 *                     then: path(delay('2d', { name: 'Give the free plan two days' }), notifyCrm),
 *                 },
 *             ],
 *         })
 *     ),
 *     exit: { reason: 'Onboarding nudge finished' },
 * })
 * ```
 */
export function workflow(options: WorkflowOptions): Workflow {
    return {
        key: options.key,
        emit: (emitOptions) =>
            compile(
                {
                    key: options.key,
                    name: options.name,
                    ...(options.description === undefined ? {} : { description: options.description }),
                    ...(options.status === undefined ? {} : { status: options.status }),
                    ...(options.exitCondition === undefined ? {} : { exitCondition: options.exitCondition }),
                    ...(options.variables === undefined ? {} : { variables: options.variables }),
                    trigger: options.on,
                    steps: options.steps,
                    exit: options.exit,
                },
                emitOptions
            ),
    }
}
