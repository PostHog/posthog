import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import {
    aeoPromptsTopics,
    aeoPromptsTopicsMerge,
    aeoPromptsTopicsRemove,
    aeoPromptsTopicsRename,
} from '../generated/api'
import { aiVisibilityTopicsLogic } from './aiVisibilityTopicsLogic'
import { EXAMPLE_PROMPT_TOPICS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    aeoPromptsTopics: jest.fn(),
    aeoPromptsTopicsRename: jest.fn(),
    aeoPromptsTopicsMerge: jest.fn(),
    aeoPromptsTopicsRemove: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ lemonToast: { error: jest.fn(), success: jest.fn() } }))

const TEAM = String(MOCK_DEFAULT_TEAM.id)

describe('aiVisibilityTopicsLogic', () => {
    let logic: ReturnType<typeof aiVisibilityTopicsLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests()
        jest.mocked(aeoPromptsTopics).mockResolvedValue(EXAMPLE_PROMPT_TOPICS)
        logic = aiVisibilityTopicsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => logic.unmount())

    it('offers only the named topics, since prompts with no topic have nothing to rename', () => {
        expect(logic.values.namedTopics.map(({ topic }) => topic)).toEqual(['Product analytics', 'Session replay'])
    })

    it.each([
        [
            'rename',
            () => logic.actions.renameTopic('Session replay', 'Replay'),
            aeoPromptsTopicsRename,
            { topic: 'Session replay', new_topic: 'Replay' },
        ],
        [
            'merge',
            () => logic.actions.mergeTopics('Session replay', 'Product analytics'),
            aeoPromptsTopicsMerge,
            { topic: 'Session replay', into_topic: 'Product analytics' },
        ],
        [
            'remove',
            () => logic.actions.removeTopic('Session replay'),
            aeoPromptsTopicsRemove,
            { topic: 'Session replay' },
        ],
    ] as const)('sends a %s, closes the dialog and reloads the topics', async (kind, act, request, body) => {
        jest.mocked(request).mockResolvedValue({ prompts: 1, checks: 3 })
        logic.actions.openTopicDialog(kind, 'Session replay')
        jest.mocked(aeoPromptsTopics).mockClear()

        act()
        await expectLogic(logic).toFinishAllListeners()

        expect(request).toHaveBeenCalledWith(TEAM, body)
        expect(logic.values).toMatchObject({ topicDialog: null, topicChangeSaving: false, topicChangeError: null })
        expect(aeoPromptsTopics).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['shows why the API refused it', new ApiError('Conflict', 409, undefined, { detail: 'Taken.' }), 'Taken.'],
        [
            'asks to try again on a server error',
            new ApiError('Server error', 500),
            "Couldn't rename the topic. Try again.",
        ],
    ])('keeps the dialog open after a failed rename and %s', async (_name, error, message) => {
        jest.mocked(aeoPromptsTopicsRename).mockRejectedValue(error)
        logic.actions.openTopicDialog('rename', 'Session replay')

        logic.actions.renameTopic('Session replay', 'Product analytics')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            topicDialog: { kind: 'rename', topic: 'Session replay' },
            topicChangeSaving: false,
            topicChangeError: message,
        })
    })
})
