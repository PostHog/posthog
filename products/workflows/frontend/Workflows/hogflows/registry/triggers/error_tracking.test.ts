import './error_tracking'

import { HogFlowActionSchema } from '../../steps/types'
import { createExampleEventForTrigger } from '../../testEventFactory'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('Error tracking issue-created trigger', () => {
    const trigger = getRegisteredTriggerTypes().find(
        (definition) => definition.value === 'error-tracking-issue-created'
    )!

    it('builds a valid internal-event trigger with an issue-shaped, person-less test event', () => {
        const config = trigger.buildConfig()
        expect(HogFlowActionSchema.safeParse({ id: 'trigger', type: 'trigger', name: 'Trigger', config }).success).toBe(
            true
        )
        expect(config.filters).toMatchObject({
            source: 'internal-events',
            events: [{ id: '$error_tracking_issue_created', type: 'events' }],
        })
        expect(trigger.matchConfig?.(config)).toBe(true)

        const sample = createExampleEventForTrigger(config, 42, 'Issue automation')
        expect(sample.event.event).toBe('$error_tracking_issue_created')
        expect(sample.event.properties).toMatchObject({
            name: expect.any(String),
            severity: 'high',
            status: 'Active',
            fingerprint: expect.any(String),
        })
        expect(sample.person).toBeUndefined()
        expect(sample.project.id).toBe(42)
    })

    it.each([
        null,
        {},
        { type: 'event', filters: { events: [{ id: '$error_tracking_issue_created' }] } },
        { type: 'internal-event', filters: { source: 'internal-events', events: [{ id: '$slack_message_received' }] } },
        {
            type: 'internal-event',
            filters: { source: 'internal-events', events: [{ id: '$error_tracking_issue_reopened' }] },
        },
        { type: 'internal-event', filters: { source: 'internal-events', events: [null] } },
        {
            type: 'internal-event',
            filters: {
                source: 'internal-events',
                events: [{ id: '$error_tracking_issue_created' }, { id: '$slack_message_received' }],
            },
        },
    ])('does not claim another or malformed trigger: %j', (config) => {
        expect(trigger.matchConfig?.(config)).toBe(false)
    })
})
