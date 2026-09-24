import type { PropertyCondition, TriggerActionOptions, TriggerAuthoringConfig } from './definition.js'
import type { PassThroughActionConfig, SecretInputsOnly } from './steps.js'

/**
 * A trigger that starts a run for each matching event, emitted as the trigger action's
 * config.
 *
 * It fires on every occurrence, so a person who does the same thing twice enters
 * twice. Each run has a person, so person-dependent steps work.
 *
 * @param options - The event to listen for.
 * @param options.event - The event name, exactly as PostHog receives it, for example
 * `user signed up`.
 * @param options.properties - Conditions the event must also meet. Build them with
 * `eventProperty`, `person` or `group`. Omit them to match every occurrence.
 * @param options.name - The trigger action label. Defaults to `Trigger`.
 * @param options.description - What starts the workflow, shown on the trigger in the editor.
 * @returns A trigger config to pass as a workflow's `on`.
 * @example
 * ```ts
 * import { eventProperty, onEvent } from '@posthog/workflows'
 *
 * const onSignup = onEvent({ event: 'user signed up' })
 *
 * const onPricingSignup = onEvent({
 *     event: 'user signed up',
 *     properties: [eventProperty('$current_url', 'icontains', ['/pricing'])],
 * })
 * ```
 */
export function onEvent(options: {
    event: string
    properties?: readonly PropertyCondition[]
    name?: string
    description?: string
}): TriggerAuthoringConfig {
    return withTriggerMeta(options, {
        type: 'event',
        filters: {
            events: [
                {
                    id: options.event,
                    name: options.event,
                    type: 'events',
                    order: 0,
                    properties: options.properties ?? [],
                },
            ],
            properties: [],
            filter_test_accounts: false,
        },
    })
}

function withTriggerMeta(options: TriggerActionOptions, config: TriggerAuthoringConfig): TriggerAuthoringConfig {
    return Object.freeze({
        ...config,
        ...(options.name === undefined ? {} : { __workflowTriggerName: options.name }),
        ...(options.description === undefined ? {} : { __workflowTriggerDescription: options.description }),
    })
}

/**
 * A trigger that starts one run per occurrence of a cadence, emitted as the trigger
 * action's config.
 *
 * A scheduled run has no person, so use it for work that acts on its own rather than on
 * somebody. Everything that reads a person has nothing to read: `{person.properties.x}`
 * resolves to nothing wherever it appears, and a `branch` arm whose conditions read
 * person or group properties does not match, so every run takes the fall-through. Write
 * a scheduled workflow as a straight path, and branch on a trigger instead.
 *
 * The cadence itself is not part of the definition. Attach it in PostHog after the
 * workflow exists, which means a scheduled workflow pushed for the first time has no
 * cadence yet and does not run, `active` or not.
 *
 * @param options - The trigger action label and description.
 * @param options.name - The trigger action label. Defaults to `Trigger`.
 * @param options.description - What starts the workflow, shown on the trigger in the editor.
 * @returns A trigger config to pass as a workflow's `on`.
 * @example
 * ```ts
 * import { fn, onSchedule, path, workflow } from '@posthog/workflows'
 *
 * // Replace this key with your own before you push.
 * const nightlyDigest = workflow({
 *     key: 'replace-me-nightly-digest',
 *     name: 'Nightly digest',
 *     on: onSchedule(),
 *     steps: path(
 *         fn({
 *             name: 'Post the digest to Slack',
 *             templateId: 'template-slack',
 *             inputs: { text: 'Last night in numbers' },
 *         })
 *     ),
 *     exit: { reason: 'Digest posted' },
 * })
 * ```
 */
export function onSchedule(options: TriggerActionOptions = {}): TriggerAuthoringConfig {
    return withTriggerMeta(options, { type: 'schedule' })
}

/**
 * A pass-through trigger, emitted as the trigger action's config.
 *
 * Use this when a copied workflow starts from a trigger type that has no typed helper yet,
 * such as `webhook`, `manual`, `batch`, `tracking_pixel`, `data-warehouse-table`,
 * `data-warehouse-view` or `internal-event`. The config is emitted verbatim as the
 * trigger action's `config`. For webhook triggers, include the fixed source template id
 * the editor stores.
 *
 * A `secret` passed as a whole entry of `config.inputs` resolves the same way it does for
 * `step`: emit sends `{ value: <resolved> }` and reports the input as a secret input of
 * the trigger action. Use it for a credential such as a webhook trigger's auth header. A
 * secret anywhere else in the config is a refusal.
 *
 * @param config - The trigger config to emit.
 * @param options - The trigger action label and description.
 * @param options.name - The trigger action label. Defaults to `Trigger`.
 * @param options.description - What starts the workflow, shown on the trigger in the editor.
 * @returns A trigger config to pass as a workflow's `on`.
 * @throws {WorkflowError} At emit, `missing_secret` when a whole input names an unset
 * variable, and `nested_secret` when a secret sits anywhere but a whole entry of
 * `config.inputs`.
 * @example
 * ```ts
 * import { secret, trigger } from '@posthog/workflows'
 *
 * const startsFromWebhook = trigger({
 *     type: 'webhook',
 *     template_id: 'template-source-webhook',
 *     inputs: {
 *         event: { value: '{request.body.event}' },
 *         distinct_id: { value: '{request.body.distinct_id}' },
 *         auth_header: secret('INCOMING_WEBHOOK_AUTH'),
 *     },
 * })
 * ```
 */
export function trigger<C extends { readonly type: string } & PassThroughActionConfig>(
    config: C & SecretInputsOnly<C>,
    options: TriggerActionOptions = {}
): TriggerAuthoringConfig {
    return withTriggerMeta(options, config)
}
