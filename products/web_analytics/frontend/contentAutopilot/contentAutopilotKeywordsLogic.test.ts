import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoKeywordsDestroy, aeoKeywordsList } from '../generated/api'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { EXAMPLE_KEYWORDS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    aeoKeywordsDestroy: jest.fn(),
    aeoKeywordsList: jest.fn(),
    aeoKeywordsReport: jest.fn().mockResolvedValue(null),
    aeoKeywordsModifiers: jest.fn().mockResolvedValue(null),
}))

describe('contentAutopilotKeywordsLogic', () => {
    let logic: ReturnType<typeof contentAutopilotKeywordsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.mocked(aeoKeywordsDestroy).mockResolvedValue(undefined)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['closes the editor when the last keyword is removed', 1, false],
        ['keeps the editor open while keywords remain', 2, true],
    ])('%s', async (_, keywordCount, expectedOpen) => {
        const keywords = EXAMPLE_KEYWORDS.slice(0, keywordCount)
        jest.mocked(aeoKeywordsList).mockResolvedValue(keywords)
        logic = contentAutopilotKeywordsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadKeywordsSuccess'])

        logic.actions.openKeywordsModal()
        logic.actions.removeKeyword(keywords[0])
        await expectLogic(logic).toDispatchActions(['removeKeywordSuccess'])

        expect(logic.values.keywordsModalOpen).toBe(expectedOpen)
    })
})
