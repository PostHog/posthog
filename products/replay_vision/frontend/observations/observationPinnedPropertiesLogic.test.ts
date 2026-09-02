import { initKeaTests } from '~/test/init'

import {
    DEFAULT_PINNED_PROPERTIES,
    MAX_PINNED_PROPERTIES,
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

    it('drops pins the sessions table has no column for', () => {
        // One bad pin would fail the whole query, blanking every other pinned value on the page.
        logic.actions.setPinnedProperties(['$entry_utm_source', 'made_up_property'])

        expect(logic.values.queryablePinnedProperties).toEqual(['$entry_utm_source'])
    })

    it('toggles a pin on and back off', () => {
        logic.actions.setPinnedProperties([])

        logic.actions.togglePropertyPin('$entry_utm_medium')
        expect(logic.values.pinnedProperties).toEqual(['$entry_utm_medium'])

        logic.actions.togglePropertyPin('$entry_utm_medium')
        expect(logic.values.pinnedProperties).toEqual([])
    })

    it('caps how many properties can be pinned', () => {
        const tooMany = Array.from({ length: MAX_PINNED_PROPERTIES + 3 }, (_, index) => `property_${index}`)

        logic.actions.setPinnedProperties(tooMany)

        expect(logic.values.pinnedProperties).toEqual(tooMany.slice(0, MAX_PINNED_PROPERTIES))
    })
})
