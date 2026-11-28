import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { aeoBrandsDetail, aeoBrandsList, aeoPromptsRetrieve } from '../generated/api'
import type { AEOBrandApi, AEOBrandDetailApi } from '../generated/api.schemas'
import { contentAutopilotBrandDetailLogic } from './contentAutopilotBrandDetailLogic'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { EXAMPLE_PROMPTS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api')

const mockDetail = jest.mocked(aeoBrandsDetail)
const mockList = jest.mocked(aeoBrandsList)

const BRAND_ID = '01900000-0000-7000-8000-000000000002'

const detailFor = (engine: string | null): AEOBrandDetailApi => ({
    brand: {
        id: BRAND_ID,
        name: 'Rival',
        domain: 'rival.example.org',
        kind: 'competitor',
        status: 'confirmed',
        source: 'manual',
        aliases: [],
        created_at: '2026-10-01T00:00:00Z',
        updated_at: null,
    },
    domains: ['rival.example.org'],
    window_from: '2026-10-01',
    window_to: '2026-10-30',
    days: 30,
    branded: 'non_branded',
    engine,
    topic: null,
    current: {
        answers: 10,
        answers_mentioning: 4,
        visibility: 0.4,
        citation_rate: 0.1,
        average_position: 2,
        positive_share: null,
    },
    previous: null,
    latest_date: '2026-10-30',
    latest: null,
    days_with_answers: 30,
    prompts: [],
    cited_sites: [],
    sentiment: { scored: 0, positive_share: null, neutral_share: null, negative_share: null, examples: [] },
    searches: [],
})

describe('contentAutopilotBrandDetailLogic', () => {
    let logic: ReturnType<typeof contentAutopilotBrandDetailLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        mockList.mockResolvedValue({ count: 0, results: [] })
        mockDetail.mockImplementation((_, __, params) => Promise.resolve(detailFor(params?.engine ?? null)))
        logic = contentAutopilotBrandDetailLogic()
        logic.mount()
    })

    it('opens the brand of its URL over the filters, reads it again when a filter changes, and goes back to rankings', async () => {
        router.actions.push(urls.webAnalyticsContentAutopilotBrand(BRAND_ID))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.brandId).toBe(BRAND_ID)
        expect(mockDetail).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            BRAND_ID,
            expect.objectContaining({ date_from: '-30d' })
        )

        contentAutopilotFiltersLogic.actions.setEngine('openai-web-search', 'brand')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.detail?.engine).toBe('openai-web-search')

        contentAutopilotLogic.actions.setWorkspaceTab('rankings')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.brandId).toBeNull()
        expect(router.values.location.pathname).not.toContain('/brands/')
    })

    it('closes a prompt left open when the history goes back to its brand', async () => {
        jest.mocked(aeoPromptsRetrieve).mockResolvedValue(EXAMPLE_PROMPTS[0])
        router.actions.push(urls.webAnalyticsContentAutopilotBrand(BRAND_ID))
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openBrandPrompt(EXAMPLE_PROMPTS[0].id)
        await expectLogic(logic).toFinishAllListeners()

        router.actions.push(urls.webAnalyticsContentAutopilotBrand(BRAND_ID))
        await expectLogic(logic).toFinishAllListeners()

        expect(contentAutopilotPromptDetailLogic.values.promptId).toBeNull()
        expect(logic.values.brandId).toBe(BRAND_ID)
    })

    it('offers the brands of every page of the catalog in the picker', async () => {
        const competitor = (index: number): AEOBrandApi => ({
            ...detailFor(null).brand,
            id: `competitor-${index}`,
            name: `Competitor ${index}`,
        })
        mockList.mockImplementation((_, params) =>
            Promise.resolve(
                params?.kind !== 'competitor'
                    ? { count: 0, next: null, results: [] }
                    : params.offset
                      ? { count: 2, next: null, results: [competitor(2)] }
                      : { count: 2, next: 'next-page', results: [competitor(1)] }
            )
        )

        logic.actions.openBrandDetail(BRAND_ID)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.pickerBrands?.map((brand) => brand.id)).toEqual(['competitor-1', 'competitor-2'])
    })

    it('says a brand of another project is not found', async () => {
        mockDetail.mockRejectedValue(new ApiError('Not found', 404))

        logic.actions.openBrandDetail(BRAND_ID)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.detailError).toBe('not_found')
        expect(logic.values.detail).toBeNull()
    })
})
