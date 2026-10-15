import './inbox_report'

import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

describe('inbox report ready trigger', () => {
    // The editor finds the tile for a stored workflow through matchConfig, so a built config the
    // tile does not recognize reopens as a generic event trigger.
    it('recognizes the config it builds', () => {
        const triggerType = getRegisteredTriggerTypes().find((t) => t.value === 'inbox-report-ready')

        const config = triggerType?.buildConfig()

        expect(config?.filters.events).toEqual([{ id: '$inbox_report_ready', type: 'events' }])
        expect(triggerType?.matchConfig?.(config)).toBe(true)
    })
})
