import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoEnginesList, aeoEnginesPartialUpdate } from '../generated/api'
import type { AEOEngineSettingApi } from '../generated/api.schemas'
import { aiVisibilityEnginesLogic } from './aiVisibilityEnginesLogic'

jest.mock('../generated/api', () => ({
    aeoEnginesList: jest.fn(),
    aeoEnginesPartialUpdate: jest.fn(),
}))

const NO_SEARCH: AEOEngineSettingApi = {
    engine: 'claude-no-search',
    mode: 'no_search',
    available: true,
    enabled: false,
    frequency: 'daily',
}

describe('aiVisibilityEnginesLogic', () => {
    let logic: ReturnType<typeof aiVisibilityEnginesLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.mocked(aeoEnginesList).mockResolvedValue([NO_SEARCH])
        logic = aiVisibilityEnginesLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it.each([
        ['a saved change replaces the row', true, { ...NO_SEARCH, enabled: true, frequency: 'weekly' as const }],
        ['a failed save keeps the row', false, NO_SEARCH],
    ])('%s and unlocks it', async (_name, succeeds, expected) => {
        await expectLogic(logic).toDispatchActions(['loadEnginesSuccess'])
        const save = jest.mocked(aeoEnginesPartialUpdate)
        if (succeeds) {
            save.mockResolvedValue({ ...NO_SEARCH, enabled: true, frequency: 'weekly' })
        } else {
            save.mockRejectedValue(new Error('boom'))
        }

        logic.actions.updateEngine('claude-no-search', { enabled: true, frequency: 'weekly' })

        await expectLogic(logic).toDispatchActions([succeeds ? 'updateEngineSuccess' : 'updateEngineFailure'])
        expect(save).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'claude-no-search', {
            enabled: true,
            frequency: 'weekly',
        })
        expect(logic.values.engines).toEqual([expected])
        expect(logic.values.updatingEngines).toEqual([])
    })
})
