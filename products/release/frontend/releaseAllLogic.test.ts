import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { earlyAccessFeatureList } from 'products/early_access_features/frontend/generated/api'
import { experimentsList } from 'products/experiments/frontend/generated/api'

import { releasesCatalogFlagsRetrieve, releasesCatalogReleasesRetrieve, releasesList } from './generated/api'
import { ALL_PAGE_SIZE, filtersFromSearchParams, releaseAllLogic, searchParamsOfFilters } from './releaseAllLogic'
import { releaseLogic } from './releaseLogic'

const EMPTY_PAGE = { results: [], count: 0, next: null }

jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn() } }))
jest.mock('./generated/api', () => ({
    releasesList: jest.fn(),
    releasesCatalogFlagsRetrieve: jest.fn(),
    releasesCatalogReleasesRetrieve: jest.fn(),
}))
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
    created_by: null,
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
        jest.mocked(releasesCatalogReleasesRetrieve).mockResolvedValue({
            results: [{ id: 'r1', name: 'Release 1', created_at: '2026-11-07T00:00:00Z' }],
            next_cursor: null,
        } as never)
        jest.mocked(experimentsList).mockImplementation(
            async (_project, params) =>
                (params?.limit === 1
                    ? { results: [], count: 0, next: null }
                    : {
                          results:
                              params?.order === 'created_at'
                                  ? [experiment(2, 4), experiment(1, 10)]
                                  : [experiment(1, 10), experiment(2, 4)],
                          count: 2,
                          next: null,
                      }) as never
        )
        jest.mocked(releasesCatalogFlagsRetrieve).mockImplementation(async (_project, params) => {
            const days: [number, number][] =
                params?.order === 'created_at'
                    ? [
                          [4, 2],
                          [3, 6],
                          [2, 8],
                          [1, 12],
                      ]
                    : [
                          [1, 12],
                          [2, 8],
                          [3, 6],
                          [4, 2],
                      ]
            const index = (params?.offset ?? 0) / ALL_PAGE_SIZE
            const page = days.slice(index * 2, index * 2 + 2).map(([id, day]) => flag(id, day))
            return { results: page, has_more: index === 0 } as never
        })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RELEASES_AREA], { [FEATURE_FLAGS.RELEASES_AREA]: true })
        releaseLogic.mount()
        logic = releaseAllLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    it.each([
        {
            order: '-created_at' as const,
            first: ['flag-1', 'Experiment 1', 'flag-2'],
            all: ['flag-1', 'Experiment 1', 'flag-2', 'Release 1', 'flag-3', 'Experiment 2', 'flag-4'],
        },
        {
            order: 'created_at' as const,
            first: ['flag-4', 'Experiment 2', 'flag-3'],
            all: ['flag-4', 'Experiment 2', 'flag-3', 'Release 1', 'flag-2', 'Experiment 1', 'flag-1'],
        },
    ])(
        'shows only rows every source has loaded past, then fills in the rest in $order order',
        async ({ order, first, all }) => {
            if (order !== '-created_at') {
                logic.actions.setFilters({ order })
                await expectLogic(logic).toFinishAllListeners()
            }
            expect(logic.values.visibleRows.map((row) => row.name)).toEqual(first)

            logic.actions.loadMore()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.visibleRows.map((row) => row.name)).toEqual(all)
            expect(logic.values.hasMore).toBe(false)
        }
    )

    it('drops a page that answers a search the user already changed, even after returning to the same text', async () => {
        let answer: (page: unknown) => void = () => {}
        jest.mocked(releasesCatalogFlagsRetrieve).mockImplementationOnce(
            () => new Promise((done) => (answer = done)) as never
        )

        logic.actions.setFilters({ search: 'same' })
        logic.actions.setFilters({ search: 'other' })
        logic.actions.setFilters({ search: 'same' })
        answer({ results: [flag(9, 20)], has_more: false })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.visibleRows.map((row) => row.name)).not.toContain('flag-9')
    })

    it('shows the error screen when one source fails and the others find nothing', async () => {
        jest.mocked(releasesCatalogFlagsRetrieve).mockRejectedValue(new Error('down'))
        jest.mocked(experimentsList).mockResolvedValue({ results: [], count: 0, next: null } as never)
        jest.mocked(releasesCatalogReleasesRetrieve).mockResolvedValue({ results: [], next_cursor: null } as never)

        logic.actions.setFilters({ search: 'nothing' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.listState).toBe('error')
    })

    it.each([
        [{}, {}],
        [
            { type: 'experiment,bogus', owner: '3,x,0', order: 'created_at', search: ' busy ' },
            { search: 'busy', type: 'experiment', owner: '3', order: 'created_at' },
        ],
        [{ order: 'name' }, {}],
    ])('reads %j from the URL and writes it back as %j', (params, written) => {
        expect(searchParamsOfFilters(filtersFromSearchParams(params))).toEqual(written)
    })
})
