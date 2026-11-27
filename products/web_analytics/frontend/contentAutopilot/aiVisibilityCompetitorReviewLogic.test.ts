import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoBrandsCompetitorCandidates, aeoBrandsList, aeoBrandsPartialUpdate } from '../generated/api'
import type { AEOBrandApi, AEOCompetitorCandidateApi, AEOSetupJobApi } from '../generated/api.schemas'
import { aiVisibilityCompetitorReviewLogic } from './aiVisibilityCompetitorReviewLogic'
import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

jest.mock('../generated/api', () => ({
    aeoBrandsCompetitorCandidates: jest.fn(),
    aeoBrandsList: jest.fn(),
    aeoBrandsPartialUpdate: jest.fn(),
    aeoSetupContext: jest.fn(() => new Promise(() => {})),
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
        ['the project already has a confirmed competitor', async () => confirmedCompetitors(1), false],
        [
            'there is nothing to suggest',
            async () => void jest.mocked(aeoBrandsCompetitorCandidates).mockResolvedValue([]),
            true,
        ],
    ])('is hidden when %s', async (_, arrange, scansCandidates) => {
        await arrange()
        await mountLoaded()

        expect(logic.values.reviewShown).toBe(false)
        expect(aeoBrandsCompetitorCandidates).toHaveBeenCalledTimes(scansCandidates ? 1 : 0)
    })

    it.each([
        ['while the first run is in progress', true, true],
        ['without a first run in progress', false, false],
    ])('retries an empty review %s', async (_, firstRunQueued, shown) => {
        jest.useFakeTimers()
        const setup = contentAutopilotSetupLogic()
        setup.mount()
        try {
            if (firstRunQueued) {
                setup.actions.setJob({
                    id: 'job',
                    status: 'completed',
                    steps: [{ step: 'first_run', status: 'done' }],
                } as AEOSetupJobApi)
            }
            jest.mocked(aeoBrandsCompetitorCandidates).mockResolvedValueOnce([])
            logic = aiVisibilityCompetitorReviewLogic()
            logic.mount()
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.reviewShown).toBe(false)

            await jest.advanceTimersByTimeAsync(30 * 1000)

            expect(logic.values.reviewShown).toBe(shown)
        } finally {
            setup.unmount()
            jest.useRealTimers()
        }
    })

    const suggestForum = (): void => {
        const suggested = [
            { id: CANDIDATES[1].brand_id, name: 'Forum', domain: 'forum.example.org' },
            { id: '00000000-0000-4000-8000-000000000903', name: 'Quiet rival', domain: 'quiet.example.org' },
        ] as AEOBrandApi[]
        jest.mocked(aeoBrandsList).mockImplementation(async (_team, params) =>
            params?.status === 'suggested'
                ? { count: suggested.length, next: null, previous: null, results: suggested }
                : { count: 0, next: null, previous: null, results: [] }
        )
    }

    it('offers only brands the answers named, with the likely ones selected, and saves the selection on leaving', async () => {
        suggestForum()
        await mountLoaded()
        expect(logic.values.candidates.map(({ name }) => name)).toEqual(['Forum', 'Rival'])
        expect(logic.values.selectedIds).toEqual([CANDIDATES[1].brand_id])

        logic.actions.toggleCandidate(CANDIDATES[0].brand_id, true)
        const onSaved = jest.fn()
        await expectLogic(logic, () => logic.actions.confirmSelected(onSaved)).toFinishAllListeners()

        const team = String(MOCK_DEFAULT_TEAM.id)
        const confirmed = { kind: 'competitor', status: 'confirmed' }
        expect(jest.mocked(aeoBrandsPartialUpdate).mock.calls).toEqual([
            [team, CANDIDATES[1].brand_id, confirmed],
            [team, CANDIDATES[0].brand_id, confirmed],
        ])
        expect(onSaved).toHaveBeenCalledTimes(1)
        expect(logic.values.confirming).toBe(false)
    })

    it('saves an unticked suggestion as not a competitor, so rankings stop counting it', async () => {
        suggestForum()
        await mountLoaded()

        logic.actions.toggleCandidate(CANDIDATES[1].brand_id, false)
        const onSaved = jest.fn()
        await expectLogic(logic, () => logic.actions.confirmSelected(onSaved)).toFinishAllListeners()

        expect(jest.mocked(aeoBrandsPartialUpdate).mock.calls).toEqual([
            [String(MOCK_DEFAULT_TEAM.id), CANDIDATES[1].brand_id, { kind: 'unknown' }],
        ])
        expect(onSaved).toHaveBeenCalledTimes(1)
        expect(logic.values.confirming).toBe(false)
    })

    it('offers a retry when the review fails to load', async () => {
        jest.mocked(aeoBrandsList).mockRejectedValueOnce(new Error('500'))
        logic = aiVisibilityCompetitorReviewLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReviewFailure'])
        expect(logic.values.reviewFailed).toBe(true)

        suggestForum()
        await expectLogic(logic, () => logic.actions.loadReview()).toDispatchActions(['loadReviewSuccess'])
        expect(logic.values.reviewFailed).toBe(false)
        expect(logic.values.reviewShown).toBe(true)
    })

    it('stays on the step when a competitor fails to save', async () => {
        suggestForum()
        jest.mocked(aeoBrandsPartialUpdate).mockRejectedValue(new Error('500'))
        await mountLoaded()

        const onSaved = jest.fn()
        await expectLogic(logic, () => logic.actions.confirmSelected(onSaved)).toFinishAllListeners()

        expect(onSaved).not.toHaveBeenCalled()
        expect(logic.values.confirming).toBe(false)
    })

    it('leaves without saving when the project already has competitors', async () => {
        confirmedCompetitors(1)
        await mountLoaded()

        const onSaved = jest.fn()
        await expectLogic(logic, () => logic.actions.confirmSelected(onSaved)).toFinishAllListeners()

        expect(aeoBrandsPartialUpdate).not.toHaveBeenCalled()
        expect(onSaved).toHaveBeenCalledTimes(1)
    })
})
