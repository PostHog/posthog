import './github'
import './insight_alert'
import './slack'

import { PropertyOperator } from '~/types'

import { decodeInsightAlertFilters, encodeInsightAlertFilters } from './insightAlertTriggerFilters'
import { getRegisteredTriggerTypes, getTriggerDisplayType } from './triggerTypeRegistry'

describe('insight alert trigger', () => {
    const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'insight-alert')!
    const internalEvent = (id: string, properties: any[] = []): Record<string, any> => ({
        type: 'internal-event',
        filters: { source: 'internal-events', events: [{ id, type: 'events' }], properties },
    })

    it('keeps the picked alerts and any other filter through a save and reload', () => {
        const custom = { key: 'state', value: ['Firing'], operator: PropertyOperator.Exact, type: 'event' }
        const filters = { alertIds: ['0198a2f4-0000-0000-0000-000000000001'], additional: [custom] }

        expect(decodeInsightAlertFilters(encodeInsightAlertFilters(filters))).toEqual(filters)
    })

    it.each([
        ['$insight_alert_firing', 'insight-alert'],
        ['$slack_message_received', 'slack-message'],
        ['$github_event_received', 'github-event'],
    ])('a trigger on %s opens the %s tile', (eventId, tile) => {
        expect(getTriggerDisplayType(internalEvent(eventId) as any)).toBe(tile)
    })

    it.each([
        ['no alert', [], false],
        [
            'an alert',
            encodeInsightAlertFilters({ alertIds: ['0198a2f4-0000-0000-0000-000000000001'], additional: [] }),
            true,
        ],
    ])('validates a trigger with %s', (_name, properties, valid) => {
        expect(triggerType.validate!(internalEvent('$insight_alert_firing', properties))?.valid).toBe(valid)
    })
})
