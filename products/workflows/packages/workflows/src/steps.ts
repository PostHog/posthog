import type {
    ActionOutputVariables,
    Duration,
    EmailDesign,
    EmailMessage,
    JsonValue,
    PropertyCondition,
    PropertyConditionValue,
    PropertyOperator,
    SetPropertyOperator,
    StepFilters,
    ValuePropertyOperator,
} from './definition.js'
import { WorkflowError } from './errors.js'

declare const secretRefBrand: unique symbol

/**
 * A named environment variable, standing in for a value the repository must not hold.
 *
 * Build one with `secret`. Pass it as the value of a whole input of `fn`, as a whole
 * entry of `config.inputs` on `step` or `trigger`, or as `signingSecret` on `webhook`. `emit` reads
 * the variable and sends the value, so PostHog never has to recover a secret it was not
 * sent. The type is branded, so a JSON-only field does not accept one.
 */
export interface SecretRef {
    readonly __secret: string
    readonly [secretRefBrand]: true
}

/**
 * Names an environment variable to read at emit, for one input of one step or trigger.
 *
 * The name travels in the source file and the value never does. `emit` reads the
 * variable from the deployer's environment and always sends the resolved value, so a
 * rotation reaches PostHog on the next push. Pass the result as the value of a whole
 * input. A secret anywhere else is a refusal, because only the name of the variable
 * would reach PostHog, stored as plain config. That covers a secret inside a larger
 * value, in a pass-through config key other than `inputs`, in `filters` or
 * `output_variable`, and in a trigger's config outside `inputs`.
 *
 * @param envName - The environment variable to read, for example `CRM_WEBHOOK_SECRET`.
 * @returns A secret reference to use as an input value.
 * @throws {WorkflowError} At emit, `missing_secret` when the variable is unset or
 * empty, and `nested_secret` when the reference sits anywhere but a whole input.
 * @example
 * ```ts
 * import { secret, webhook } from '@posthog/workflows'
 *
 * const notifyCrm = webhook({
 *     name: 'Tell the CRM to follow up',
 *     url: 'https://example.com/hooks/onboarding',
 *     signingSecret: secret('CRM_WEBHOOK_SECRET'),
 * })
 * ```
 */
export function secret(envName: string): SecretRef {
    return Object.freeze({ __secret: envName }) as SecretRef
}

/**
 * Whether a value is a secret reference.
 *
 * Use it to inspect a step's inputs before emit, for example to report which variables
 * a file needs.
 *
 * @param value - Any value.
 * @returns True when the value came from `secret`.
 */
export function isSecretRef(value: unknown): value is SecretRef {
    return typeof value === 'object' && value !== null && typeof (value as SecretRef).__secret === 'string'
}

/**
 * One or more property conditions, all of which must hold.
 *
 * The tuple takes at least one condition, so a branch that decides nothing does not
 * compile. Build each condition with `person`, `eventProperty` or `group`.
 */
export type Conditions = readonly [PropertyCondition, ...PropertyCondition[]]

/**
 * An ordered run of one or more steps. Build one with `path`.
 *
 * A path is a value like a step, so one path declared once is placed in two branches.
 * The tuple takes at least one step, so an empty branch does not compile.
 */
export type Path = readonly [Step, ...Step[]]

/** One arm of a branch: its label, the conditions that take it, and the path it runs. */
export interface BranchSpec {
    /** The label PostHog shows on the arm in the editor. */
    readonly name: string
    /** The conditions that send a person down this arm. */
    readonly when: Conditions
    /** The steps this arm runs before it rejoins the path after the branch. */
    readonly then: Path
}

interface StepBase {
    readonly name: string
    /** An explicit action id to use instead of the slug of `name`. */
    readonly id?: string
    readonly description?: string
}

interface ActionFieldOptions {
    readonly filters?: StepFilters | null
    readonly on_error?: 'continue' | 'abort' | null
    readonly output_variable?: ActionOutputVariables | null
}

export type PassThroughActionConfig = {
    readonly [key: string]: JsonValue | Readonly<Record<string, JsonValue | SecretRef>> | undefined
    readonly inputs?: Readonly<Record<string, JsonValue | SecretRef>>
}

/**
 * Narrows a pass-through config so a `secret` is accepted only as a whole entry of
 * `inputs`. The index signature of `PassThroughActionConfig` has to admit the type of
 * `inputs`, so alone it admits a secret one level down in any key.
 */
export type SecretInputsOnly<C> = {
    readonly [K in keyof C]: K extends 'inputs' ? Readonly<Record<string, JsonValue | SecretRef>> : JsonValue
}

/** The options `step` takes. */
export interface PassThroughStepOptions extends StepBase, ActionFieldOptions {
    readonly type: string
    readonly config: PassThroughActionConfig
    readonly branches?: readonly Path[]
}

/**
 * A step: one thing a workflow does, as a value.
 *
 * A step carries no position until placed, so the same value placed in two places
 * makes two actions in the definition. Build one with `delay`, `fn`, `webhook`, `email`
 * or `branch`, then place it with `path`.
 */
export type Step =
    | Readonly<StepBase & { kind: 'delay'; duration: Duration }>
    | Readonly<
          StepBase & { kind: 'function'; templateId: string; inputs: Readonly<Record<string, JsonValue | SecretRef>> }
      >
    | Readonly<StepBase & { kind: 'email'; email: EmailMessage }>
    | Readonly<StepBase & { kind: 'branch'; branches: readonly [BranchSpec, ...BranchSpec[]] }>
    | Readonly<
          StepBase &
              ActionFieldOptions & {
                  kind: 'passthrough'
                  type: string
                  config: PassThroughActionConfig
                  branches: readonly Path[]
              }
      >

function withMeta<T extends object>(
    options: { readonly id?: string; readonly description?: string },
    step: T
): Readonly<T & { id?: string; description?: string }> {
    return Object.freeze({
        ...step,
        ...(options.id === undefined ? {} : { id: options.id }),
        ...(options.description === undefined ? {} : { description: options.description }),
    })
}

/**
 * A step that waits, emitted as a `delay` action.
 *
 * Write the wait in the largest unit that fits, because PostHog caps the amount per
 * unit at 60s, 60m, 24h and 30d and reports nothing when it clamps. `1.5h` waits 90
 * minutes; `90m` is a refusal.
 *
 * @param duration - How long to wait, as a number and a unit.
 * @param options - The step's label, and an optional action id.
 * @param options.name - The label, which also gives the action id its slug.
 * @param options.id - Pins the action id, so a rename keeps the id a live run is on.
 * @param options.description - What the step is for, shown on the step in the editor.
 * @returns A step value to place with `path`.
 * @throws {WorkflowError} At emit, `invalid_duration` for a value the type let through,
 * and `duration_over_unit_cap` for a wait PostHog would clamp.
 * @example
 * ```ts
 * import { delay } from '@posthog/workflows'
 *
 * const waitADay = delay('1d', { name: 'Wait a day' })
 * const waitAnHourAndAHalf = delay('1.5h', { name: 'Wait ninety minutes' })
 * ```
 */
export function delay(duration: Duration, options: { name: string; id?: string; description?: string }): Step {
    return withMeta(options, { kind: 'delay' as const, name: options.name, duration })
}

/**
 * A step that runs any PostHog destination template, emitted as a `function` action.
 *
 * This is the escape hatch, and it reaches every template the typed helpers do not
 * cover. The compiler does not know a template's input schema, so PostHog validates
 * the inputs when the push lands. Find a template id and its inputs with the
 * `cdp-function-templates-list` and `cdp-function-templates-retrieve` endpoints rather
 * than guessing, because the catalog changes as integrations are added.
 *
 * Each input value is wrapped as `{ value: ... }` in the definition, which is what
 * makes hog templating such as `{person.properties.email}` resolve at run time.
 *
 * @param options - The template to run and the inputs to give it.
 * @param options.name - The label, which also gives the action id its slug.
 * @param options.id - Pins the action id, so a rename keeps the id a live run is on.
 * @param options.description - What the step is for, shown on the step in the editor.
 * @param options.templateId - A live template id, for example `template-slack`.
 * @param options.inputs - Input values keyed by the template's input schema. Pass a
 * `secret` as the value of a whole input.
 * @returns A step value to place with `path`.
 * @throws {WorkflowError} At emit, `nested_secret` when a secret sits inside a larger
 * input value.
 * @example
 * ```ts
 * import { fn } from '@posthog/workflows'
 *
 * const postToSlack = fn({
 *     name: 'Post to Slack',
 *     templateId: 'template-slack',
 *     inputs: { text: 'A new signup: {person.properties.email}' },
 * })
 * ```
 */
export function fn(options: {
    name: string
    id?: string
    description?: string
    templateId: string
    inputs: Readonly<Record<string, JsonValue | SecretRef>>
}): Step {
    return withMeta(options, {
        kind: 'function' as const,
        name: options.name,
        templateId: options.templateId,
        inputs: options.inputs,
    })
}

/**
 * A step that calls an HTTP endpoint, emitted as a `function` action on
 * `template-webhook`.
 *
 * The signing secret is the one credential in this package's surface. Give it a
 * `secret` so the value stays out of the repository.
 *
 * @param options - The request to send.
 * @param options.name - The label, which also gives the action id its slug.
 * @param options.id - Pins the action id, so a rename keeps the id a live run is on.
 * @param options.description - What the step is for, shown on the step in the editor.
 * @param options.url - The endpoint to call.
 * @param options.method - The HTTP method. Defaults to `POST`.
 * @param options.body - The JSON body. Values may hold hog templating. Defaults to `{}`.
 * @param options.headers - Extra request headers.
 * @param options.signingSecret - The HMAC key PostHog signs the request with. Omit it
 * only when the endpoint needs no proof the call came from PostHog.
 * @returns A step value to place with `path`.
 * @throws {WorkflowError} At emit, `missing_secret` when the signing secret's variable
 * is unset, and `nested_secret` when a secret sits inside the body or the headers.
 * @example
 * ```ts
 * import { secret, webhook } from '@posthog/workflows'
 *
 * const notifyCrm = webhook({
 *     name: 'Tell the CRM to follow up',
 *     url: 'https://example.com/hooks/onboarding',
 *     body: { distinct_id: '{event.distinct_id}', plan: '{person.properties.plan}' },
 *     signingSecret: secret('CRM_WEBHOOK_SECRET'),
 * })
 * ```
 */
export function webhook(options: {
    name: string
    id?: string
    description?: string
    url: string
    method?: 'POST' | 'PUT' | 'PATCH' | 'GET' | 'DELETE'
    body?: Record<string, JsonValue>
    headers?: Record<string, string>
    signingSecret?: SecretRef
}): Step {
    const inputs: Record<string, JsonValue | SecretRef> = {
        url: options.url,
        method: options.method ?? 'POST',
        body: options.body ?? {},
    }
    if (options.headers !== undefined) {
        inputs.headers = options.headers
    }
    if (options.signingSecret !== undefined) {
        inputs.signing_secret = options.signingSecret
    }
    return fn({
        ...(options.id === undefined ? {} : { id: options.id }),
        ...(options.description === undefined ? {} : { description: options.description }),
        name: options.name,
        templateId: 'template-webhook',
        inputs,
    })
}

/**
 * The sender of an email step: which of the project's verified senders to send from, and
 * an optional address and name to show.
 */
export interface EmailSenderOptions {
    /**
     * The ids of the project's email integrations to send from, at least one and at
     * most ten. With several, PostHog picks one per run. The ids are listed under
     * Workflows, Channels, in the project.
     */
    readonly integrationIds: readonly [number, ...number[]]
    /**
     * The address to send from. It sits on the verified domain of every sender in
     * `integrationIds`, or is hog templating that resolves to such an address. Omit it
     * to send from the integration's own address.
     */
    readonly email?: string
    /** The sender name shown beside the address. */
    readonly name?: string
}

// The same wrap PostHog builds in `posthog/cdp/validation.py` for an html body that
// arrives without a design. Its ids are fixed there so the wrap is deterministic, and the
// SDK copies them so the design it sends is the design PostHog stores.
function htmlWrapDesign(html: string): EmailDesign {
    return {
        counters: { u_row: 1, u_column: 1, u_content_html: 1 },
        schemaVersion: 16,
        body: {
            id: 'html-wrap-body',
            headers: [],
            footers: [],
            rows: [
                {
                    id: 'html-wrap-row',
                    cells: [1],
                    columns: [
                        {
                            id: 'html-wrap-column',
                            contents: [
                                {
                                    id: 'html-wrap-content',
                                    type: 'html',
                                    values: {
                                        html,
                                        _meta: { htmlID: 'u_content_html_1', htmlClassNames: 'u_content_html' },
                                    },
                                },
                            ],
                            values: { _meta: { htmlID: 'u_column_1', htmlClassNames: 'u_column' } },
                        },
                    ],
                    values: { _meta: { htmlID: 'u_row_1', htmlClassNames: 'u_row' } },
                },
            ],
            values: {},
        },
    }
}

/**
 * A step that sends an email, emitted as a `function_email` action.
 *
 * The content is inline, and there is no way to reference a saved library template,
 * because PostHog copies a referenced template into the workflow when it saves and
 * every later push would then report a change. The sender is one of the project's
 * email integrations, named by id: PostHog refuses to save an email step without one,
 * and the runtime sends from nothing else.
 *
 * @param options - The message to send.
 * @param options.name - The label, which also gives the action id its slug.
 * @param options.id - Pins the action id, so a rename keeps the id a live run is on.
 * @param options.description - What the step is for, shown on the step in the editor.
 * @param options.from - Which verified senders to send from, and the address and name
 * to show. See `EmailSenderOptions`.
 * @param options.to - The recipient. Usually hog templating such as
 * `{person.properties.email}`.
 * @param options.subject - The subject line.
 * @param options.text - The plain-text body, which every client can show.
 * @param options.html - The HTML body. The step also carries it as the design the
 * visual editor opens, built the way PostHog builds it, so the stored message is the
 * pushed message.
 * @param options.preheader - The preview line some clients show beside the subject.
 * @returns A step value to place with `path`.
 * @throws {WorkflowError} At emit, `invalid_email_sender` when `from.integrationIds`
 * is empty, holds more than ten ids, or holds a value that is not an integer;
 * `invalid_sender_address` when `from.email` is a literal that is not an address; and
 * `nested_secret` when a secret reaches any field, because an email step takes no
 * credential.
 * @example
 * ```ts
 * import { email } from '@posthog/workflows'
 *
 * const welcome = email({
 *     name: 'Welcome the paid customer',
 *     from: { integrationIds: [12], name: 'The Example team' },
 *     to: '{person.properties.email}',
 *     subject: 'Welcome aboard',
 *     text: 'Thanks for upgrading. Here is how to get started.',
 *     html: '<p>Thanks for upgrading. Here is how to get started.</p>',
 * })
 * ```
 */
export function email(options: {
    name: string
    id?: string
    description?: string
    from: EmailSenderOptions
    to: string
    subject: string
    text: string
    html: string
    preheader?: string
}): Step {
    // The CLI evaluates a file without type-checking, so a sender written for another shape,
    // or none, arrives here. It is read loosely and passed on, so emit refuses it with a reason.
    const sender: Partial<EmailSenderOptions> = options.from ?? {}
    const ids: readonly number[] = Array.isArray(sender.integrationIds) ? sender.integrationIds : []
    const message: EmailMessage = {
        from: {
            integrationId: ids[0] as number,
            integrationIds: [...ids],
            ...(sender.email === undefined ? {} : { email: sender.email }),
            ...(sender.name === undefined ? {} : { name: sender.name }),
        },
        to: { email: options.to },
        subject: options.subject,
        text: options.text,
        html: options.html,
        design: htmlWrapDesign(options.html),
        ...(options.preheader === undefined ? {} : { preheader: options.preheader }),
    }
    return withMeta(options, { kind: 'email' as const, name: options.name, email: message })
}

/**
 * A step that sends a person down one of several paths, emitted as a
 * `conditional_branch` action.
 *
 * PostHog tries the arms in order and takes the first whose conditions all hold. A
 * person who matches no arm follows the fall-through, which is the step after the
 * branch. Each arm's path rejoins there too, so a branch is a detour rather than a
 * split that never closes.
 *
 * Conditions here read person and group properties. PostHog refuses an event filter in
 * a branch, so gate on an event with the trigger instead. A run started by `onSchedule`
 * has no person, so every arm that reads a person property fails to match and every run
 * takes the fall-through.
 *
 * @param options - The branch's label and its arms.
 * @param options.name - The label, which also gives the action id its slug.
 * @param options.id - Pins the action id, so a rename keeps the id a live run is on.
 * @param options.description - What the step is for, shown on the step in the editor.
 * @param options.branches - One arm or more, tried in order. `emit` derives each arm's
 * edge index from its position, so a condition and the edge that runs it always agree.
 * @returns A step value to place with `path`.
 * @throws {WorkflowError} At emit, `empty_path` when an arm's `then` holds no step.
 * @example
 * ```ts
 * import { branch, delay, email, path, person } from '@posthog/workflows'
 *
 * const welcome = email({
 *     name: 'Welcome the paid customer',
 *     to: '{person.properties.email}',
 *     subject: 'Welcome aboard',
 *     text: 'Thanks for upgrading.',
 *     html: '<p>Thanks for upgrading.</p>',
 * })
 *
 * const whichPlan = branch({
 *     name: 'Which plan?',
 *     branches: [
 *         { name: 'Paid plan', when: [person('plan', 'exact', ['pro'])], then: path(welcome) },
 *         {
 *             name: 'Free plan',
 *             when: [person('plan', 'exact', ['free'])],
 *             then: path(delay('2d', { name: 'Give the free plan two days' })),
 *         },
 *     ],
 * })
 * ```
 */
export function branch(options: {
    name: string
    id?: string
    description?: string
    branches: readonly [BranchSpec, ...BranchSpec[]]
}): Step {
    return withMeta(options, { kind: 'branch' as const, name: options.name, branches: options.branches })
}

/**
 * A pass-through step, emitted as the action type and config you give it.
 *
 * Use this when a copied workflow uses an action type that has no typed helper yet, such
 * as `function_sms`, `wait_until_condition`, `wait_until_time_window`, `random_cohort_branch`
 * or a `delay` shape the typed `delay` helper does not cover. The `config` is emitted
 * verbatim, except that a `secret` passed as a whole entry of `config.inputs` resolves
 * the same way it does for `fn`. A secret anywhere else is a refusal: inside an input
 * value, in any other config key, in `filters` or in `output_variable`.
 *
 * Set `branches` for action types whose branch edges are part of the graph, for example
 * `random_cohort_branch` or `wait_until_condition`. The SDK emits one branch edge to
 * each path in order, using `index: 0`, `index: 1` and so on, plus the fall-through
 * `continue` edge to the next step.
 *
 * @param options - The action type, label, config and optional branch paths.
 * @param options.type - The PostHog action type to emit. `trigger` and `exit` are reserved.
 * @param options.name - The label, which also gives the action id its slug.
 * @param options.id - Pins the action id, so a rename keeps the id a live run is on.
 * @param options.description - What the step is for, shown on the step in the editor.
 * @param options.config - The action config to emit.
 * @param options.filters - Property filters gating this action, as stored by the editor.
 * @param options.on_error - Whether a run continues or aborts when this action fails.
 * @param options.output_variable - Where the action result is stored for later steps.
 * @param options.branches - Branch paths to emit as indexed branch edges.
 * @returns A step value to place with `path`.
 * @throws {WorkflowError} `reserved_action_type` when `type` is `trigger` or `exit`; at
 * emit, `missing_secret` when a whole input names an unset variable, and `nested_secret`
 * when a secret sits anywhere but a whole entry of `config.inputs`.
 * @example
 * ```ts
 * import { path, step } from '@posthog/workflows'
 *
 * const sendText = step({
 *     type: 'function_sms',
 *     name: 'Send a text message',
 *     config: {
 *         template_id: 'template-twilio',
 *         inputs: { message: { value: 'Thanks for signing up.' } },
 *     },
 * })
 *
 * const split = step({
 *     type: 'random_cohort_branch',
 *     name: 'Split traffic',
 *     config: { cohorts: [{ percentage: 50, name: 'A' }, { percentage: 50, name: 'B' }] },
 *     branches: [path(sendText), path(sendText)],
 * })
 * ```
 */
export function step<C extends PassThroughActionConfig>(
    options: PassThroughStepOptions & { readonly config: C & SecretInputsOnly<C> }
): Step {
    if (options.type === 'trigger' || options.type === 'exit') {
        throw new WorkflowError({
            status: 'reserved_action_type',
            message: `The action type "${options.type}" is reserved.`,
            why: 'Every workflow has one trigger action and one exit action, and the SDK emits them from workflow options.',
            fix:
                options.type === 'trigger'
                    ? 'Use trigger(...) in the workflow on field.'
                    : 'Use the workflow exit field.',
        })
    }

    return Object.freeze({
        kind: 'passthrough' as const,
        type: options.type,
        name: options.name,
        config: options.config,
        branches: options.branches ?? [],
        ...(options.id === undefined ? {} : { id: options.id }),
        ...(options.description === undefined ? {} : { description: options.description }),
        ...(options.filters === undefined ? {} : { filters: options.filters }),
        ...(options.on_error === undefined ? {} : { on_error: options.on_error }),
        ...(options.output_variable === undefined ? {} : { output_variable: options.output_variable }),
    })
}

/**
 * Places steps in order, and returns the path they form.
 *
 * A **placement** is one appearance of a step in a path. Placement decides the edges,
 * and it decides the action id of a step that appears more than once: the first
 * placement takes the slug of the step name, and each later placement in graph order
 * takes a numbered id such as `tell_the_crm_2`. So one step value declared once and
 * placed twice becomes two actions in the definition, not one shared action.
 *
 * Graph order walks a branch's arms before the step that follows the branch, so adding
 * a step at the end of a path leaves every earlier placement's action id alone.
 *
 * `path` builds the value and does nothing else, so an array literal of the same steps
 * is the same path. Write `path(...)`, which reads as placement and keeps the non-empty
 * rule visible at the call.
 *
 * @param steps - One step or more, in the order they run.
 * @returns A path value, which goes in a workflow's `steps` or a branch arm's `then`.
 * @example
 * ```ts
 * import { delay, path } from '@posthog/workflows'
 *
 * const coolOff = delay('1d', { name: 'Cool off' })
 *
 * // `coolOff` is placed twice, so the definition holds `cool_off` and `cool_off_2`.
 * const twoWaits = path(coolOff, delay('2d', { name: 'Wait two more days' }), coolOff)
 * ```
 */
export function path(...steps: Path): Path {
    return steps
}

type PropertyConditionBuilder = {
    (key: string, operator: SetPropertyOperator): PropertyCondition
    (key: string, operator: ValuePropertyOperator, value: PropertyConditionValue): PropertyCondition
}

function condition(type: 'event' | 'person'): PropertyConditionBuilder {
    return ((key: string, operator: PropertyOperator, value?: PropertyConditionValue): PropertyCondition =>
        value === undefined
            ? { key, operator, value: operator as SetPropertyOperator, type }
            : { key, operator, value, type }) as PropertyConditionBuilder
}

/**
 * A condition on a person property, for a branch arm or an event trigger.
 *
 * @param key - The person property, for example `plan`.
 * @param operator - How to compare. `is_set` and `is_not_set` take no value.
 * @param value - The values to compare against. Several values match any of them.
 * @returns One property condition.
 * @example
 * ```ts
 * import { person } from '@posthog/workflows'
 *
 * const onPaidPlan = person('plan', 'exact', ['pro', 'enterprise'])
 * const hasEmail = person('email', 'is_set')
 * ```
 */
export const person = condition('person')

/**
 * A condition on a property of the event that started the run.
 *
 * Use it in an event trigger's `properties`. PostHog refuses an event-based filter
 * inside a branch, so a branch reads person and group properties instead.
 *
 * @param key - The event property, for example `$current_url`.
 * @param operator - How to compare. `is_set` and `is_not_set` take no value.
 * @param value - The values to compare against. Several values match any of them.
 * @returns One property condition.
 * @example
 * ```ts
 * import { eventProperty, onEvent } from '@posthog/workflows'
 *
 * const onPricingSignup = onEvent({
 *     event: 'user signed up',
 *     properties: [eventProperty('$current_url', 'icontains', ['/pricing'])],
 * })
 * ```
 */
export const eventProperty = condition('event')

/**
 * A condition on a group property, for a branch arm or an event trigger.
 *
 * @param groupTypeIndex - The PostHog group type index, for example `0` for the first group type.
 * @param key - The group property, for example `industry`.
 * @param operator - How to compare. `is_set` and `is_not_set` take no value.
 * @param value - The values to compare against. Several values match any of them.
 * @returns One property condition.
 * @example
 * ```ts
 * import { group } from '@posthog/workflows'
 *
 * const enterpriseAccount = group(0, 'tier', 'exact', ['enterprise'])
 * ```
 */
export function group(groupTypeIndex: number, key: string, operator: SetPropertyOperator): PropertyCondition
export function group(
    groupTypeIndex: number,
    key: string,
    operator: ValuePropertyOperator,
    value: PropertyConditionValue
): PropertyCondition
export function group(
    groupTypeIndex: number,
    key: string,
    operator: PropertyOperator,
    value?: PropertyConditionValue
): PropertyCondition {
    return value === undefined
        ? { key, operator, value: operator as SetPropertyOperator, type: 'group', group_type_index: groupTypeIndex }
        : { key, operator, value, type: 'group', group_type_index: groupTypeIndex }
}
