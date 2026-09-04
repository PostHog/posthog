import { expectLogic } from 'kea-test-utils'

import api from '~/lib/api'
import { initKeaTests } from '~/test/init'

import { PinnedProperty, observationPinnedPropertiesLogic } from './observationPinnedPropertiesLogic'
import { observationSessionPropertiesLogic, pinnedPropertyId } from './observationSessionPropertiesLogic'

jest.mock('~/lib/api')

describe('observationSessionPropertiesLogic', () => {
    const SESSION_ID = '0195e2a1-0000-7000-8000-000000000001'
    const PINS: PinnedProperty[] = [
        { key: '$screen_width', type: 'event' },
        { key: '$geoip_country_code', type: 'event' },
        { key: 'is_paying', type: 'person' },
        { key: 'plan', type: 'person' },
    ]

    let logic: ReturnType<typeof observationSessionPropertiesLogic.build>

    async function loadRow(row: unknown[]): Promise<void> {
        jest.mocked(api.queryHogQL).mockResolvedValue({ results: [row] } as any)
        logic = observationSessionPropertiesLogic({ sessionId: SESSION_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        observationPinnedPropertiesLogic.mount()
        observationPinnedPropertiesLogic.actions.setPinnedProperties(PINS)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('reads back every value as text, whatever type the query answers with', async () => {
        // HogQL answers with the stored type, so a pinned number or boolean used to reach the strip
        // as a number or a boolean and take the whole observation page down with it.
        await loadRow([1440, 'GB', false, null])

        expect(logic.values.sessionProperties).toEqual({
            [pinnedPropertyId(PINS[0])]: '1440',
            [pinnedPropertyId(PINS[1])]: 'GB',
            [pinnedPropertyId(PINS[2])]: 'false',
            [pinnedPropertyId(PINS[3])]: null,
        })
    })

    it('keeps a zero, and reads an empty value as absent', async () => {
        await loadRow([0, '', [1, 2], null])

        expect(logic.values.sessionProperties).toEqual({
            [pinnedPropertyId(PINS[0])]: '0',
            [pinnedPropertyId(PINS[1])]: null,
            [pinnedPropertyId(PINS[2])]: '[1,2]',
            [pinnedPropertyId(PINS[3])]: null,
        })
    })
})
