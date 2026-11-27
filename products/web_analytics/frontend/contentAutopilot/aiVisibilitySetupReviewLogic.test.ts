import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoKeywordsList, aeoPromptsList } from '../generated/api'
import type { AEOPromptApi } from '../generated/api.schemas'
import { aiVisibilitySetupReviewLogic } from './aiVisibilitySetupReviewLogic'

jest.mock('../generated/api', () => ({
    aeoPromptsList: jest.fn(),
    aeoKeywordsList: jest.fn(async () => []),
    aeoSetupContext: jest.fn(() => new Promise(() => {})),
}))

describe('aiVisibilitySetupReviewLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it.each([
        ['prompts', 'promptsFailed', 'loadPrompts'],
        ['keywords', 'keywordsFailed', 'loadKeywords'],
    ] as const)(
        'offers a retry when the %s fail to load, so the step leaves its skeleton',
        async (_name, flag, load) => {
            const list = load === 'loadPrompts' ? aeoPromptsList : aeoKeywordsList
            jest.mocked(aeoPromptsList).mockResolvedValue({
                count: 0,
                next: null,
                previous: null,
                results: [],
            } as Awaited<ReturnType<typeof aeoPromptsList>>)
            jest.mocked(list).mockRejectedValue(new Error('500'))
            const logic = aiVisibilitySetupReviewLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions([`${load}Failure`])
            expect(logic.values[flag]).toBe(true)

            if (load === 'loadPrompts') {
                jest.mocked(aeoPromptsList).mockResolvedValue({
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                } as Awaited<ReturnType<typeof aeoPromptsList>>)
            } else {
                jest.mocked(aeoKeywordsList).mockResolvedValue([])
            }
            await expectLogic(logic, () => logic.actions[load]()).toDispatchActions([`${load}Success`])
            expect(logic.values[flag]).toBe(false)
            expect(logic.values.prompts ?? ([] as AEOPromptApi[])).toEqual([])
            logic.unmount()
        }
    )
})
