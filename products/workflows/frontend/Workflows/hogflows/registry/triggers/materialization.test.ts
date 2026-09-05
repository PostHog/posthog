import './materialization'

import { PropertyOperator } from '~/types'

import {
    MaterializationOutcome,
    decodeMaterializationFilters,
    encodeMaterializationFilters,
    isMaterializationJobTriggerConfig,
} from './materializationTriggerFilters'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('materialization job trigger', () => {
    const getTriggerType = (): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'materialization-job')
        if (!triggerType) {
            throw new Error('Materialization job trigger type not registered')
        }
        return triggerType
    }

    it.each<{ name: string; viewName: string | null; outcome: MaterializationOutcome }>([
        { name: 'any view, any outcome', viewName: null, outcome: 'any' },
        { name: 'any view, failed only', viewName: null, outcome: 'failed' },
        { name: 'one view, completed only', viewName: 'daily_revenue', outcome: 'completed' },
    ])('filters survive a save and reload for $name', ({ viewName, outcome }) => {
        // The editor reads its controls back out of the stored filters, so an outcome that
        // encodes to something decode can't recognize silently resets the control on reopen.
        const filters = { viewName, outcome, additional: [] }
        expect(decodeMaterializationFilters(encodeMaterializationFilters(filters))).toEqual(filters)
    })

    it('keeps filters the native controls do not own', () => {
        const custom = { key: 'error', value: ['timeout'], operator: PropertyOperator.IContains, type: 'event' }
        const encoded = encodeMaterializationFilters({
            viewName: 'daily_revenue',
            outcome: 'failed',
            additional: [custom],
        })

        expect(encoded).toContainEqual(custom)
        expect(decodeMaterializationFilters(encoded).additional).toEqual([custom])
    })

    it('builds a config that its own matcher recognizes', () => {
        const config = getTriggerType().buildConfig()

        expect(isMaterializationJobTriggerConfig(config)).toBe(true)
        expect(decodeMaterializationFilters(config.filters.properties).outcome).toBe('failed')
    })

    it('does not claim another internal event', () => {
        expect(
            isMaterializationJobTriggerConfig({
                type: 'internal-event',
                filters: { source: 'internal-events', events: [{ id: '$slack_message_received', type: 'events' }] },
            })
        ).toBe(false)
    })
})
