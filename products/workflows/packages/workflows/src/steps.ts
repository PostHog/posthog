import type { Duration, EmailMessage, PropertyCondition, PropertyOperator, PropertyType } from './definition.js'

/**
 * A named environment variable, standing in for a value the repository must not hold.
 *
 * Build one with `secret`. Pass it as the value of a whole input of `fn` or as
 * `signingSecret` on `webhook`. `emit` reads the variable and sends the value, so
 * PostHog never has to recover a secret it was not sent.
 */
export interface SecretRef {
    readonly __secret: string
}

/**
 * Names an environment variable to read at emit, for one input of one step.
 *
 * The name travels in the source file and the value never does. `emit` reads the
 * variable from the deployer's environment and always sends the resolved value, so a
 * rotation reaches PostHog on the next push. Pass the result as the value of a whole
 * input. A secret inside a larger value is a refusal, because only the name of the
 * variable would reach PostHog.
 *
 * @param envName - The environment variable to read, for example `CRM_WEBHOOK_SECRET`.
 * @returns A secret reference to use as an input value.
 * @throws {WorkflowError} At emit, `missing_secret` when the variable is unset or
 * empty, and `nested_secret` when the reference sits inside a larger value.
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
    return Object.freeze({ __secret: envName })
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
    readonly id?: string
}

/**
 * A step: one thing a workflow does, as a value.
 *
 * A step carries no action id and no position, so the same value placed in two places
 * makes two actions in the definition. Build one with `delay`, `fn`, `webhook`, `email`
 * or `branch`, then place it with `path`.
 */
export type Step =
    | Readonly<StepBase & { kind: 'delay'; duration: Duration }>
    | Readonly<StepBase & { kind: 'function'; templateId: string; inputs: Readonly<Record<string, unknown>> }>
    | Readonly<StepBase & { kind: 'email'; email: EmailMessage }>
    | Readonly<StepBase & { kind: 'branch'; branches: readonly [BranchSpec, ...BranchSpec[]] }>

function withId<T extends object>(options: { readonly id?: string }, step: T): Readonly<T & { id?: string }> {
    return Object.freeze(options.id === undefined ? step : { ...step, id: options.id })
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
export function delay(duration: Duration, options: { name: string; id?: string }): Step {
    return withId(options, { kind: 'delay' as const, name: options.name, duration })
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
    templateId: string
    inputs: Readonly<Record<string, unknown>>
}): Step {
    return withId(options, {
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
    url: string
    method?: 'POST' | 'PUT' | 'PATCH' | 'GET' | 'DELETE'
    body?: Record<string, unknown>
    headers?: Record<string, string>
    signingSecret?: SecretRef
}): Step {
    const inputs: Record<string, unknown> = {
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
        name: options.name,
        templateId: 'template-webhook',
        inputs,
    })
}

/**
 * A step that sends an email, emitted as a `function_email` action.
 *
 * The content is inline, and there is no way to reference a saved library template,
 * because PostHog copies a referenced template into the workflow when it saves and
 * every later push would then report a change. An email needs no credential: PostHog
 * resolves the project's email integration with a verified domain when it sends.
 *
 * @param options - The message to send.
 * @param options.name - The label, which also gives the action id its slug.
 * @param options.id - Pins the action id, so a rename keeps the id a live run is on.
 * @param options.to - The recipient. Usually hog templating such as
 * `{person.properties.email}`.
 * @param options.subject - The subject line.
 * @param options.text - The plain-text body, which every client can show.
 * @param options.html - The HTML body.
 * @param options.preheader - The preview line some clients show beside the subject.
 * @param options.fromIntegrationId - Pins one sender by integration id. Omit it to let
 * PostHog resolve the project's verified sender, which keeps one file usable in two
 * projects.
 * @returns A step value to place with `path`.
 * @throws {WorkflowError} At emit, `nested_secret` when a secret reaches any field,
 * because an email step takes no credential.
 * @example
 * ```ts
 * import { email } from '@posthog/workflows'
 *
 * const welcome = email({
 *     name: 'Welcome the paid customer',
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
    to: string
    subject: string
    text: string
    html: string
    preheader?: string
    fromIntegrationId?: number
}): Step {
    const message: EmailMessage = {
        from: options.fromIntegrationId === undefined ? {} : { integrationId: options.fromIntegrationId },
        to: { email: options.to },
        subject: options.subject,
        text: options.text,
        html: options.html,
        ...(options.preheader === undefined ? {} : { preheader: options.preheader }),
    }
    return withId(options, { kind: 'email' as const, name: options.name, email: message })
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
export function branch(options: { name: string; id?: string; branches: readonly [BranchSpec, ...BranchSpec[]] }): Step {
    return withId(options, { kind: 'branch' as const, name: options.name, branches: options.branches })
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

function condition(type: PropertyType) {
    return (
        key: string,
        operator: PropertyOperator,
        value?: readonly (string | number | boolean)[]
    ): PropertyCondition => (value === undefined ? { key, operator, type } : { key, operator, value, type })
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
 * @param key - The group property, for example `industry`.
 * @param operator - How to compare. `is_set` and `is_not_set` take no value.
 * @param value - The values to compare against. Several values match any of them.
 * @returns One property condition.
 * @example
 * ```ts
 * import { group } from '@posthog/workflows'
 *
 * const enterpriseAccount = group('tier', 'exact', ['enterprise'])
 * ```
 */
export const group = condition('group')
