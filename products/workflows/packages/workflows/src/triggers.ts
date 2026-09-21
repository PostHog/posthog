import type { PropertyCondition, TriggerConfig } from './definition.js'

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
export function onEvent(options: { event: string; properties?: readonly PropertyCondition[] }): TriggerConfig {
    return {
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
    }
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
export function onSchedule(): TriggerConfig {
    return { type: 'schedule' }
}
