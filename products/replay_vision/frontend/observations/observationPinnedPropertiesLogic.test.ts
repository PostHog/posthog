import { initKeaTests } from '~/test/init'

import {
    DEFAULT_PINNED_PROPERTIES,
    MAX_PINNED_PROPERTIES,
    PinnedProperty,
    observationPinnedPropertiesLogic,
} from './observationPinnedPropertiesLogic'

describe('observationPinnedPropertiesLogic', () => {
    let logic: ReturnType<typeof observationPinnedPropertiesLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = observationPinnedPropertiesLogic()
        logic.mount()
        logic.actions.setPinnedProperties(DEFAULT_PINNED_PROPERTIES)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('drops session pins the sessions table has no column for', () => {
        // The sessions table has a fixed schema, so one bad column fails the query and blanks every
        // other pinned value. Event and person bags read back null instead, so they stay.
        logic.actions.setPinnedProperties([
            { key: '$entry_utm_source', type: 'session' },
            { key: 'made_up_property', type: 'session' },
            { key: 'made_up_property', type: 'event' },
            { key: 'plan', type: 'person' },
        ])

        expect(logic.values.queryablePinnedProperties).toEqual([
            { key: '$entry_utm_source', type: 'session' },
            { key: 'made_up_property', type: 'event' },
            { key: 'plan', type: 'person' },
        ])
    })

    it('treats the same key in two namespaces as two separate pins', () => {
        // $browser exists as both an event property and a person property, so unpinning one must
        // not silently remove the other.
        logic.actions.setPinnedProperties([])
        logic.actions.togglePropertyPin('$browser', 'event')
        logic.actions.togglePropertyPin('$browser', 'person')
        expect(logic.values.pinnedProperties).toHaveLength(2)

        logic.actions.togglePropertyPin('$browser', 'event')
        expect(logic.values.pinnedProperties).toEqual([{ key: '$browser', type: 'person' }])
    })

    it('toggles a pin on and back off', () => {
        logic.actions.setPinnedProperties([])

        logic.actions.togglePropertyPin('$entry_utm_medium', 'session')
        expect(logic.values.pinnedProperties).toEqual([{ key: '$entry_utm_medium', type: 'session' }])

        logic.actions.togglePropertyPin('$entry_utm_medium', 'session')
        expect(logic.values.pinnedProperties).toEqual([])
    })

    it('caps how many properties can be pinned', () => {
        const tooMany: PinnedProperty[] = Array.from({ length: MAX_PINNED_PROPERTIES + 3 }, (_, index) => ({
            key: `property_${index}`,
            type: 'event',
        }))

        logic.actions.setPinnedProperties(tooMany)

        expect(logic.values.pinnedProperties).toEqual(tooMany.slice(0, MAX_PINNED_PROPERTIES))
    })
})
