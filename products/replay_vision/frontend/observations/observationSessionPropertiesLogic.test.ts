import { expectLogic } from 'kea-test-utils'

import api from '~/lib/api'
import { initKeaTests } from '~/test/init'

import { observationPinnedPropertiesLogic } from './observationPinnedPropertiesLogic'
import { observationSessionPropertiesLogic, toDisplayValue } from './observationSessionPropertiesLogic'

jest.mock('~/lib/api')

const SESSION_ID = '01994a1e-4a3f-7000-8000-000000000000'

describe('observationSessionPropertiesLogic', () => {
    let logic: ReturnType<typeof observationSessionPropertiesLogic.build>

    const mockApi = api as jest.Mocked<typeof api>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // A property keeps its own type through HogQL, so the strip used to call startsWith on the
    // number $browser_version reads back as.
    it.each([
        [143, '143'],
        [0, '0'],
        [false, 'false'],
        ['Chrome', 'Chrome'],
        [['a', 'b'], '["a","b"]'],
        [null, null],
        [undefined, null],
        ['', null],
    ])('reads %p as %p', (value, expected) => {
        expect(toDisplayValue(value)).toBe(expected)
    })

    it('renders non-string property values as text', async () => {
        observationPinnedPropertiesLogic.mount()
        observationPinnedPropertiesLogic.actions.setPinnedProperties([
            { key: '$browser_version', type: 'event' },
            { key: '$browser', type: 'event' },
        ])
        mockApi.queryHogQL.mockResolvedValue({ results: [[143, 'Chrome']] } as any)

        logic = observationSessionPropertiesLogic({ sessionId: SESSION_ID })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sessionProperties).toEqual({
            'event:$browser_version': '143',
            'event:$browser': 'Chrome',
        })
    })
})
