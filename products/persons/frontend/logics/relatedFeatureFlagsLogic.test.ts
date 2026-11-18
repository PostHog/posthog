import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { NEW_FLAG } from 'scenes/feature-flags/featureFlagLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagReleaseType, FeatureFlagType } from '~/types'

import { relatedFeatureFlagsLogic } from './relatedFeatureFlagsLogic'

const createMockFlag = (overrides: Partial<FeatureFlagType>): FeatureFlagType => ({
    ...NEW_FLAG,
    created_at: '2023-01-01T00:00:00Z',
    ...overrides,
})

const MOCK_FLAGS: FeatureFlagType[] = [
    createMockFlag({
        id: 1,
        key: 'flag-1',
        name: 'Flag 1',
        active: true,
    }),
    createMockFlag({
        id: 2,
        key: 'flag-2',
        name: 'Flag 2',
        active: false,
    }),
    createMockFlag({
        id: 3,
        key: 'flag-3',
        name: 'Flag 3',
        active: true,
        filters: {
            ...NEW_FLAG.filters,
            multivariate: { variants: [{ key: 'a', rollout_percentage: 100 }] },
        },
    }),
]

const OFF_PAGE_FLAG = createMockFlag({
    id: 101,
    key: 'flag-101',
    name: 'Flag 101',
    active: true,
})

const MOCK_EVALUATION_REASONS = {
    'flag-1': { value: true, evaluation: { reason: 'condition_match', condition_index: 0 } },
    'flag-2': { value: false, evaluation: { reason: 'no_condition_match' } },
    'flag-3': { value: true, evaluation: { reason: 'condition_match', condition_index: 1 } },
    'flag-101': { value: true, evaluation: { reason: 'condition_match', condition_index: 0 } },
}

describe('relatedFeatureFlagsLogic', () => {
    let logic: ReturnType<typeof relatedFeatureFlagsLogic.build>
    let flagsLogic: ReturnType<typeof featureFlagsLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        flagsLogic?.unmount()
    })

    describe('server-side filtering', () => {
        // One handler that filters by the request's actual query params — MSW ignores
        // query strings in handler URLs, so pre-baked per-filter handlers never keyed
        // off the params anyway.
        const setupMocks = (): void => {
            // oxlint-disable-next-line react-hooks/rules-of-hooks
            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/`]: ({ request }) => {
                        const params = new URL(request.url).searchParams
                        const active = params.get('active')
                        const type = params.get('type')
                        let filteredFlags = [...MOCK_FLAGS]
                        if (active !== null) {
                            filteredFlags = filteredFlags.filter((flag) => flag.active === (active === 'true'))
                        }
                        if (type === 'boolean') {
                            filteredFlags = filteredFlags.filter((flag) => !flag.filters.multivariate?.variants?.length)
                        } else if (type === 'multivariant') {
                            filteredFlags = filteredFlags.filter(
                                (flag) => !!flag.filters.multivariate?.variants?.length
                            )
                        }
                        return [200, { results: filteredFlags, count: filteredFlags.length }]
                    },
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/evaluation_reasons`]:
                        MOCK_EVALUATION_REASONS,
                },
            })
        }

        beforeEach(() => {
            setupMocks()
            flagsLogic = featureFlagsLogic()
            flagsLogic.mount()
            logic = relatedFeatureFlagsLogic({ distinctId: 'test-user' })
            logic.mount()
        })

        it('should filter flags by type=boolean on server side', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle })
            }).toFinishAllListeners()

            expect(logic.values.featureFlags.results.map((flag) => flag.key)).toEqual(['flag-1', 'flag-2'])
            expect(logic.values.mappedRelatedFeatureFlags).toHaveLength(2)
            expect(logic.values.mappedRelatedFeatureFlags.map((f) => f.key)).toEqual(['flag-1', 'flag-2'])
            expect(flagsLogic.values.filters.type).toBeUndefined()
        })

        it('should filter flags by type=multivariant on server side', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.Variants })
            }).toFinishAllListeners()

            expect(logic.values.featureFlags.results.map((flag) => flag.key)).toEqual(['flag-3'])
            expect(logic.values.mappedRelatedFeatureFlags).toHaveLength(1)
            expect(logic.values.mappedRelatedFeatureFlags[0].key).toEqual('flag-3')
        })

        it('should filter flags by active=true on server side', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'true' })
            }).toFinishAllListeners()

            expect(logic.values.featureFlags.results.map((flag) => flag.key)).toEqual(['flag-1', 'flag-3'])
            expect(logic.values.featureFlags.results.every((flag) => flag.active)).toBe(true)
        })

        it('should filter flags by active=false on server side', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'false' })
            }).toFinishAllListeners()

            expect(logic.values.featureFlags.results.map((flag) => flag.key)).toEqual(['flag-2'])
            expect(logic.values.featureFlags.results[0].active).toBe(false)
        })

        it('should combine multiple filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle, active: 'true' })
            }).toFinishAllListeners()

            expect(logic.values.featureFlags.results.map((flag) => flag.key)).toEqual(['flag-1'])
        })

        it('should clear type filter when replace=true and type not in new filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ type: FeatureFlagReleaseType.ReleaseToggle, active: 'true' })
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setFilters({ active: 'true' }, true)
            }).toFinishAllListeners()

            expect(logic.values.featureFlags.results.map((flag) => flag.key)).toEqual(['flag-1', 'flag-3'])
        })

        it('should still apply client-side filtering for reason filter', async () => {
            setupMocks()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setFilters({ reason: 'condition_match' })
            })

            const filtered = logic.values.filteredMappedFlags
            expect(filtered).toHaveLength(2)
            expect(filtered.map((f) => f.key)).toEqual(['flag-1', 'flag-3'])
        })

        it('should reload evaluation reasons when feature flags are reloaded', async () => {
            setupMocks()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.loadRelatedFeatureFlags()
            })
                .toDispatchActions(['loadFeatureFlags'])
                .toFinishAllListeners()

            await expectLogic(logic).toFinishAllListeners()
        })
    })

    describe('isolated server-side search', () => {
        let requestedSearches: (string | null)[]

        const setupMocks = (): void => {
            requestedSearches = []
            // oxlint-disable-next-line react-hooks/rules-of-hooks
            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/`]: ({ request }) => {
                        const search = new URL(request.url).searchParams.get('search')
                        requestedSearches.push(search)
                        return search
                            ? [200, { results: [OFF_PAGE_FLAG], count: 1 }]
                            : [200, { results: MOCK_FLAGS, count: 101 }]
                    },
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/evaluation_reasons`]:
                        MOCK_EVALUATION_REASONS,
                },
            })
        }

        beforeEach(() => {
            setupMocks()
            flagsLogic = featureFlagsLogic()
            flagsLogic.mount()
            logic = relatedFeatureFlagsLogic({ distinctId: 'test-user' })
            logic.mount()
        })

        it('does not write the search term into the shared featureFlagsLogic', async () => {
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('flag-1')
            }).toFinishAllListeners()

            expect(logic.values.searchTerm).toEqual('flag-1')
            // The shared list logic must stay on its default search — a leak here surfaced as an
            // empty flags list showing a term the user never typed on that scene.
            expect(flagsLogic.values.filters.search).toBeUndefined()
        })

        it('finds a matching flag outside the loaded page', async () => {
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.mappedRelatedFeatureFlags.map((flag) => flag.key)).not.toContain('flag-101')

            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('flag-101')
            }).toFinishAllListeners()

            expect(requestedSearches).toContain('flag-101')
            expect(logic.values.filteredMappedFlags.map((flag) => flag.key)).toEqual(['flag-101'])
            expect(logic.values.pagination).toEqual(expect.objectContaining({ currentPage: 1, entryCount: 1 }))
        })
    })

    describe('load errors', () => {
        beforeEach(() => {
            // oxlint-disable-next-line react-hooks/rules-of-hooks
            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/`]: [
                        200,
                        { results: MOCK_FLAGS, count: MOCK_FLAGS.length },
                    ],
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/evaluation_reasons`]: [
                        503,
                        { error: 'Feature flag evaluation service is temporarily unavailable. Please try again.' },
                    ],
                },
            })
            flagsLogic = featureFlagsLogic()
            flagsLogic.mount()
            logic = relatedFeatureFlagsLogic({ distinctId: 'test-user' })
            logic.mount()
        })

        it('sets loadError on a failed load and clears it once a retry succeeds', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.loadError).toBe(true)
            // No pagination controls next to the error state — the flags list count would
            // otherwise keep the arrows active over an empty table
            expect(logic.values.pagination).toBeUndefined()

            useMocks({
                get: {
                    [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/evaluation_reasons`]:
                        MOCK_EVALUATION_REASONS,
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadRelatedFeatureFlags()
            }).toFinishAllListeners()
            expect(logic.values.loadError).toBe(false)
            expect(logic.values.pagination).toEqual(
                expect.objectContaining({ controlled: true, entryCount: MOCK_FLAGS.length })
            )
        })
    })
})
