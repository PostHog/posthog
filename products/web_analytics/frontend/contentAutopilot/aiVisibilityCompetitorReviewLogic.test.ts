import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoBrandsCompetitorCandidates, aeoBrandsList, aeoBrandsPartialUpdate } from '../generated/api'
import type { AEOBrandApi, AEOCompetitorCandidateApi } from '../generated/api.schemas'
import { aiVisibilityCompetitorReviewLogic } from './aiVisibilityCompetitorReviewLogic'

jest.mock('../generated/api', () => ({
    aeoBrandsCompetitorCandidates: jest.fn(),
    aeoBrandsList: jest.fn(),
    aeoBrandsPartialUpdate: jest.fn(),
}))

const CANDIDATES: AEOCompetitorCandidateApi[] = [
    {
        brand_id: '00000000-0000-4000-8000-000000000901',
        name: 'Rival',
        domain: 'rival.example.org',
        answers_naming: 40,
        answers_citing: 12,
    },
    {
        brand_id: '00000000-0000-4000-8000-000000000902',
        name: 'Forum',
        domain: 'forum.example.org',
        answers_naming: 9,
        answers_citing: 30,
    },
]

const confirmedCompetitors = (count: number): void => {
    jest.mocked(aeoBrandsList).mockResolvedValue({ count, next: null, previous: null, results: [] })
}

describe('aiVisibilityCompetitorReviewLogic', () => {
    let logic: ReturnType<typeof aiVisibilityCompetitorReviewLogic.build>

    const mountLoaded = async (): Promise<void> => {
        logic = aiVisibilityCompetitorReviewLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReviewSuccess'])
    }

    beforeEach(() => {
        jest.clearAllMocks()
        localStorage.clear()
        initKeaTests()
        jest.mocked(aeoBrandsCompetitorCandidates).mockResolvedValue(CANDIDATES)
        jest.mocked(aeoBrandsPartialUpdate).mockResolvedValue({} as AEOBrandApi)
        confirmedCompetitors(0)
    })

    afterEach(() => logic.unmount())

    it.each([
        ['confirmed', { kind: 'competitor', status: 'confirmed' }, { confirmed: 1, rejected: 0 }],
        ['rejected', { status: 'ignored' }, { confirmed: 0, rejected: 1 }],
    ] as const)('saves a %s candidate and takes it off the list', async (decision, change, decisions) => {
        await mountLoaded()
        expect(logic.values.reviewShown).toBe(true)

        logic.actions.reviewCandidate(CANDIDATES[0].brand_id, decision)
        await expectLogic(logic).toDispatchActions(['reviewCandidateSuccess'])

        expect(aeoBrandsPartialUpdate).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            CANDIDATES[0].brand_id,
            change
        )
        expect(logic.values.candidates).toEqual([CANDIDATES[1]])
        expect(logic.values.decisions).toEqual(decisions)
        expect(logic.values.updatingIds).toEqual([])
    })

    it('keeps the candidate when the save fails', async () => {
        jest.mocked(aeoBrandsPartialUpdate).mockRejectedValue(new Error('500'))
        await mountLoaded()

        logic.actions.reviewCandidate(CANDIDATES[0].brand_id, 'confirmed')
        await expectLogic(logic).toDispatchActions(['reviewCandidateFailure'])

        expect(logic.values.candidates).toEqual(CANDIDATES)
        expect(logic.values.decisions).toEqual({ confirmed: 0, rejected: 0 })
        expect(logic.values.updatingIds).toEqual([])
    })

    it('stays up after the last suggestion is reviewed, until the person finishes', async () => {
        jest.mocked(aeoBrandsCompetitorCandidates).mockResolvedValue([CANDIDATES[0]])
        await mountLoaded()

        logic.actions.reviewCandidate(CANDIDATES[0].brand_id, 'confirmed')
        await expectLogic(logic).toDispatchActions(['reviewCandidateSuccess'])
        expect(logic.values.reviewShown).toBe(true)

        logic.actions.finishReview()
        expect(logic.values.reviewShown).toBe(false)
    })

    it.each([
        ['the project already has a confirmed competitor', 1, CANDIDATES],
        ['there is nothing to suggest', 0, []],
    ])('is hidden when %s', async (_, confirmed, candidates) => {
        confirmedCompetitors(confirmed)
        jest.mocked(aeoBrandsCompetitorCandidates).mockResolvedValue(candidates)
        await mountLoaded()

        expect(logic.values.reviewShown).toBe(false)
    })
})
