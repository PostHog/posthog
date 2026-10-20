import './alert'

import { decodeAlertFilters, encodeAlertFilters } from './alertTriggerFilters'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('alert transition trigger', () => {
    const alertTriggerType = (): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'alert-transition')
        if (!triggerType) {
            throw new Error('Alert trigger type not registered')
        }
        return triggerType
    }

    const internalEvent = (eventId: string, properties: Record<string, any>[] = []): Record<string, any> => ({
        type: 'internal-event',
        filters: { source: 'internal-events', events: [{ id: eventId, type: 'events' }], properties },
    })

    it.each([
        { name: 'alerts and transitions', filters: { alertIds: ['a-1', 'a-2'], transitions: ['firing', 'resolved'] } },
        { name: 'alerts with every transition', filters: { alertIds: ['a-1'], transitions: [] } },
    ])('keeps $name across a save and reload', ({ filters }) => {
        expect(decodeAlertFilters(encodeAlertFilters(filters))).toEqual(filters)
    })

    it.each([
        { eventId: '$alert_transition', claimed: true },
        { eventId: '$slack_message_received', claimed: false },
        { eventId: '$github_event_received', claimed: false },
    ])('claims only its own event: $eventId', ({ eventId, claimed }) => {
        expect(alertTriggerType().matchConfig?.(internalEvent(eventId))).toBe(claimed)
    })

    it('refuses a trigger that names no alert', () => {
        const triggerType = alertTriggerType()
        expect(triggerType.validate?.(triggerType.buildConfig())).toEqual({
            valid: false,
            errors: { alertIds: 'Pick at least one alert' },
        })
        expect(
            triggerType.validate?.(
                internalEvent('$alert_transition', encodeAlertFilters({ alertIds: ['a-1'], transitions: [] }))
            )
        ).toEqual({ valid: true, errors: {} })
    })
})
