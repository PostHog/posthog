import type { PropertyCondition, TriggerConfig } from './definition.js'

/** An event trigger. It fires on every matching occurrence. */
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

/** A schedule trigger. The cadence is attached in PostHog and is not part of the definition. */
export function onSchedule(): TriggerConfig {
    return { type: 'schedule' }
}
