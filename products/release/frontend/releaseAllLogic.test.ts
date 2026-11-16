import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { earlyAccessFeatureList } from 'products/early_access_features/frontend/generated/api'
import { experimentsList } from 'products/experiments/frontend/generated/api'

import { releasesCatalogFlagsRetrieve, releasesList } from './generated/api'
import { ALL_PAGE_SIZE, releaseAllLogic } from './releaseAllLogic'
import { releaseLogic } from './releaseLogic'

const EMPTY_PAGE = { results: [], count: 0, next: null }

jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn() } }))
jest.mock('./generated/api', () => ({ releasesList: jest.fn(), releasesCatalogFlagsRetrieve: jest.fn() }))
jest.mock('products/feature_flags/frontend/generated/api', () => ({
    featureFlagsList: jest.fn(async () => EMPTY_PAGE),
    featureFlagsRetrieve: jest.fn(),
    scheduledChangesList: jest.fn(async () => EMPTY_PAGE),
}))
jest.mock('products/experiments/frontend/generated/api', () => ({ experimentsList: jest.fn() }))
jest.mock('products/workflows/frontend/generated/api', () => ({
    hogFlowsList: jest.fn(async () => EMPTY_PAGE),
    hogFlowsSendCalendarRetrieve: jest.fn(async () => ({ flows: [] })),
}))
jest.mock('products/early_access_features/frontend/generated/api', () => ({
    earlyAccessFeatureList: jest.fn(),
    earlyAccessFeatureRetrieve: jest.fn(),
}))

const flag = (id: number, day: number): Record<string, unknown> => ({
    id,
    key: `flag-${id}`,
    active: true,
    created_at: `2026-11-${String(day).padStart(2, '0')}T00:00:00Z`,
})
const experiment = (id: number, day: number): Record<string, unknown> => ({
    id,
    name: `Experiment ${id}`,
    created_at: `2026-11-${String(day).padStart(2, '0')}T00:00:00Z`,
})

describe('releaseAllLogic', () => {
    let logic: ReturnType<typeof releaseAllLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.mocked(releasesList).mockResolvedValue(EMPTY_PAGE as never)
        jest.mocked(earlyAccessFeatureList).mockResolvedValue(EMPTY_PAGE as never)
        jest.mocked(experimentsList).mockImplementation(
            async (_project, params) =>
                (params?.limit === 1
                    ? { results: [], count: 0, next: null }
                    : { results: [experiment(1, 10), experiment(2, 4)], count: 2, next: null }) as never
        )
        jest.mocked(releasesCatalogFlagsRetrieve).mockImplementation(
            async (_project, params) =>
                (params?.offset === ALL_PAGE_SIZE
                    ? { results: [flag(3, 6), flag(4, 2)], has_more: false }
                    : { results: [flag(1, 12), flag(2, 8)], has_more: true }) as never
        )
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RELEASES_AREA], { [FEATURE_FLAGS.RELEASES_AREA]: true })
        releaseLogic.mount()
        logic = releaseAllLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    it('shows only rows every source has loaded past, and the next page fills in the rest in order', async () => {
        expect(logic.values.visibleRows.map((row) => row.name)).toEqual(['flag-1', 'Experiment 1', 'flag-2'])

        logic.actions.loadMore()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.visibleRows.map((row) => row.name)).toEqual([
            'flag-1',
            'Experiment 1',
            'flag-2',
            'flag-3',
            'Experiment 2',
            'flag-4',
        ])
        expect(logic.values.hasMore).toBe(false)
    })

    it('holds back older rows while early access is still scanning pages without search matches', async () => {
        jest.mocked(earlyAccessFeatureList).mockResolvedValue({
            results: [{ id: 'a', name: 'Unrelated', stage: 'beta', created_at: '2026-11-11T00:00:00Z' }],
            count: 2,
            next: 'more',
        } as never)
        jest.mocked(releasesCatalogFlagsRetrieve).mockResolvedValue({
            results: [flag(1, 12), flag(2, 8)],
            has_more: false,
        } as never)

        logic.actions.setAppliedSearch('flag')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.visibleRows.map((row) => row.name)).toEqual(['flag-1'])
    })

    it('drops a page that answers a search the user already changed, even after returning to the same text', async () => {
        let answer: (page: unknown) => void = () => {}
        jest.mocked(releasesCatalogFlagsRetrieve).mockImplementationOnce(
            () => new Promise((done) => (answer = done)) as never
        )

        logic.actions.setAppliedSearch('same')
        logic.actions.setAppliedSearch('other')
        logic.actions.setAppliedSearch('same')
        answer({ results: [flag(9, 20)], has_more: false })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.visibleRows.map((row) => row.name)).not.toContain('flag-9')
    })
})
