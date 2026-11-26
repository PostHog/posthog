import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoEnginesList, aeoPromptsTopics } from '../generated/api'
import { contentAutopilotFilterBarLogic } from './contentAutopilotFilterBarLogic'
import { EXAMPLE_PROMPT_TOPICS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    aeoEnginesList: jest.fn(),
    aeoEnginesPartialUpdate: jest.fn(),
    aeoPromptsTopics: jest.fn(),
}))

describe('contentAutopilotFilterBarLogic', () => {
    let logic: ReturnType<typeof contentAutopilotFilterBarLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.mocked(aeoEnginesList).mockResolvedValue([])
        jest.mocked(aeoPromptsTopics).mockResolvedValue(EXAMPLE_PROMPT_TOPICS)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['the same spelling', 'Session replay', 'Session replay', []],
        ['another letter case', 'session REPLAY', 'Session replay', []],
        ['a topic no prompt has now', 'Retired', 'Retired', [{ value: 'Retired', label: 'Retired' }]],
    ])('selects a topic from a link with %s', async (_, linkTopic, expectedValue, extraOptions) => {
        router.actions.push(`/web/content-autopilot?topic=${encodeURIComponent(linkTopic)}`)
        logic = contentAutopilotFilterBarLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPromptTopicsSuccess'])

        expect(logic.values.topicValue).toEqual(expectedValue)
        expect(logic.values.topicOptions).toEqual([
            { value: null, label: 'All topics' },
            { value: '', label: 'No topic (1)' },
            { value: 'Product analytics', label: 'Product analytics (2)' },
            { value: 'Session replay', label: 'Session replay (1)' },
            ...extraOptions,
        ])
    })
})
