import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoPromptsCitations, aeoPromptsRetrieve } from '../generated/api'
import { type CitationsLookup, contentAutopilotCitationsModalLogic } from './contentAutopilotCitationsModalLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { EXAMPLE_PROMPT_CITATIONS, EXAMPLE_PROMPTS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    aeoPromptsCitations: jest.fn(),
    aeoPromptsRetrieve: jest.fn(),
    aeoPromptsStats: jest.fn(),
    aeoPromptsChecks: jest.fn(),
}))

const mockCitations = jest.mocked(aeoPromptsCitations)

const page = (offset: number, limit: number): ReturnType<typeof aeoPromptsCitations> =>
    Promise.resolve({
        count: EXAMPLE_PROMPT_CITATIONS.length,
        next: null,
        previous: null,
        results: EXAMPLE_PROMPT_CITATIONS.slice(offset, offset + limit),
    })

const OWN_PAGE: CitationsLookup = {
    kind: 'url',
    value: 'https://example.com/docs/product-analytics',
    days: 30,
    branded: 'non_branded',
}

describe('contentAutopilotCitationsModalLogic', () => {
    let logic: ReturnType<typeof contentAutopilotCitationsModalLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = contentAutopilotCitationsModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads the answers for the lookup, appends the next page and knows an own page', async () => {
        mockCitations.mockImplementation((_, params) => page(params?.offset ?? 0, 2))

        logic.actions.openCitations(OWN_PAGE, 'rankings-pages')
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ hasMoreCitations: true, isOwnPage: true })
        expect(mockCitations).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            url: OWN_PAGE.value,
            days: 30,
            branded: 'non_branded',
            include_answer_text: true,
            limit: 10,
            offset: 0,
        })

        logic.actions.loadMoreCitations()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ hasMoreCitations: false })
        expect(mockCitations).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ offset: 2 })
        )
        expect(logic.values.citations?.results.map((citation) => citation.id)).toEqual(
            EXAMPLE_PROMPT_CITATIONS.map((citation) => citation.id)
        )
    })

    it('drops the previous lookup and ignores its late answer', async () => {
        let resolveFirst: (value: Awaited<ReturnType<typeof aeoPromptsCitations>>) => void = () => {}
        mockCitations
            .mockImplementationOnce(() => new Promise((resolve) => (resolveFirst = resolve)))
            .mockImplementationOnce(() => page(1, 1))

        logic.actions.openCitations(OWN_PAGE, 'rankings-pages')
        logic.actions.openCitations({ ...OWN_PAGE, kind: 'search', value: 'funnels' }, 'overview-searches')
        resolveFirst({ count: 3, next: null, previous: null, results: EXAMPLE_PROMPT_CITATIONS })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.citations).toEqual({ count: 3, results: [EXAMPLE_PROMPT_CITATIONS[1]] })
        expect(logic.values.isOwnPage).toBe(false)
    })

    it('closes and opens a prompt from the list on the prompts tab', async () => {
        mockCitations.mockImplementation(() => page(0, 10))
        jest.mocked(aeoPromptsRetrieve).mockResolvedValue(EXAMPLE_PROMPTS[1])
        logic.actions.openCitations(OWN_PAGE, 'rankings-pages')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openCitationPrompt(EXAMPLE_PROMPTS[1].id)

        await expectLogic(logic).toMatchValues({ lookup: null, citations: null })
        expect(contentAutopilotLogic.values.workspaceTab).toEqual('prompts')
        expect(contentAutopilotPromptDetailLogic.values.promptId).toEqual(EXAMPLE_PROMPTS[1].id)
    })
})
