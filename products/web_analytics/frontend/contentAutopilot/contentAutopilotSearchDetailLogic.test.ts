import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoPromptsSearchDetail } from '../generated/api'
import type { AEOPromptSetSearchDetailApi } from '../generated/api.schemas'
import {
    type ContentAutopilotSearchDetailLogicProps,
    contentAutopilotSearchDetailLogic,
} from './contentAutopilotSearchDetailLogic'

jest.mock('../generated/api', () => ({ aeoPromptsSearchDetail: jest.fn() }))

const mockSearchDetail = jest.mocked(aeoPromptsSearchDetail)

const ROW: ContentAutopilotSearchDetailLogicProps = {
    query: 'acme pricing',
    dateFrom: '2026-10-01',
    dateTo: '2026-10-30',
    branded: 'non_branded',
    engine: null,
    topic: 'Pricing',
}

const detailFor = (engines: string[]): AEOPromptSetSearchDetailApi => ({
    query: 'acme pricing',
    window_from: '2026-10-01',
    window_to: '2026-10-30',
    answers: 4,
    prompts: 2,
    cited: 1,
    engines,
    domains_cited: 1,
    target_rank: 1,
    domains: [{ domain: 'example.com', answers: 1, share_of_answers: 0.25, is_target: true }],
    related_searches: [],
    keywords: [],
    top_prompts: [],
})

describe('contentAutopilotSearchDetailLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('reads each row over the filters of the report, and a filter change reads it again', async () => {
        mockSearchDetail.mockImplementation((_, params) =>
            Promise.resolve(detailFor(params.engine ? [params.engine] : ['claude-web-search', 'openai-web-search']))
        )

        const allEngines = contentAutopilotSearchDetailLogic(ROW)
        allEngines.mount()
        await expectLogic(allEngines).toFinishAllListeners()
        const oneEngine = contentAutopilotSearchDetailLogic({ ...ROW, engine: 'openai-web-search' })
        oneEngine.mount()
        await expectLogic(oneEngine).toFinishAllListeners()

        expect(mockSearchDetail).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            search: 'acme pricing',
            date_from: '2026-10-01',
            date_to: '2026-10-30',
            branded: 'non_branded',
            topic: 'Pricing',
        })
        expect(mockSearchDetail).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            search: 'acme pricing',
            date_from: '2026-10-01',
            date_to: '2026-10-30',
            branded: 'non_branded',
            engine: 'openai-web-search',
            topic: 'Pricing',
        })
        expect(allEngines.values.detail?.engines).toEqual(['claude-web-search', 'openai-web-search'])
        expect(oneEngine.values.detail?.engines).toEqual(['openai-web-search'])
        allEngines.unmount()
        oneEngine.unmount()
    })

    it('reports a failed read so the row can offer a retry, and clears it on the retry', async () => {
        mockSearchDetail
            .mockRejectedValueOnce(new Error('boom'))
            .mockResolvedValueOnce(detailFor(['claude-web-search']))

        const logic = contentAutopilotSearchDetailLogic(ROW)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ detailFailed: true, detail: null })

        logic.actions.loadDetail()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ detailFailed: false })
        expect(logic.values.detail?.answers).toBe(4)
        logic.unmount()
    })
})
