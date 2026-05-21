import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayLensesLogic } from './replayLensesLogic'
import { LensConfig, LensType, ReplayLens } from './types'

function defaultConfigForType(lensType: LensType): LensConfig {
    if (lensType === 'summarizer') {
        return { prompt: 'Summarize this session.', length: 'medium' }
    }
    if (lensType === 'classifier') {
        return { prompt: 'Tag this session.', tags: [], multi_label: true }
    }
    if (lensType === 'scorer') {
        return { prompt: 'Score this session.', scale: { min: 0, max: 10 } }
    }
    return { prompt: 'Did the user struggle?' }
}

function makeLens(overrides: Partial<ReplayLens> = {}): ReplayLens {
    const lensType: LensType = overrides.lens_type ?? 'monitor'
    const base = {
        id: 'lens-1',
        name: 'Confused checkout',
        description: '',
        enabled: true,
        sampling_rate: 0.1,
        query: null,
        provider: 'google',
        model: 'gemini-3-flash',
        emits_signals: false,
        lens_version: 1,
        last_swept_at: '2026-05-12T00:00:00Z',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
        created_by: null,
        lens_type: lensType,
        lens_config: defaultConfigForType(lensType),
    }
    return { ...base, ...overrides } as ReplayLens
}

describe('replayLensesLogic', () => {
    let logic: ReturnType<typeof replayLensesLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/vision/lenses/': { results: [] },
                '/api/environments/:team/vision/quota/': () => [404, {}],
            },
        })
        initKeaTests()
        logic = replayLensesLogic({ tabId: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    const lenses: ReplayLens[] = [
        makeLens({ id: 'a', name: 'Confused checkout', lens_type: 'monitor', enabled: true }),
        makeLens({ id: 'b', name: 'Power user behavior', lens_type: 'classifier', enabled: false }),
        makeLens({ id: 'c', name: 'Refund summarizer', lens_type: 'summarizer', enabled: true }),
    ]

    it.each([
        { name: 'no filters returns all', search: '', enabled: [], types: [], expected: ['a', 'b', 'c'] },
        { name: 'search by name', search: 'checkout', enabled: [], types: [], expected: ['a'] },
        { name: 'search by prompt fragment', search: 'struggle', enabled: [], types: [], expected: ['a'] },
        { name: 'enabled filter', search: '', enabled: ['enabled' as const], types: [], expected: ['a', 'c'] },
        { name: 'disabled filter', search: '', enabled: ['disabled' as const], types: [], expected: ['b'] },
        {
            name: 'lens type filter',
            search: '',
            enabled: [],
            types: ['classifier' as LensType, 'summarizer' as LensType],
            expected: ['b', 'c'],
        },
        {
            name: 'combined search + enabled',
            search: 'refund',
            enabled: ['enabled' as const],
            types: [],
            expected: ['c'],
        },
    ])('filteredLenses: $name', async ({ search, enabled, types, expected }) => {
        await expectLogic(logic, () => {
            logic.actions.loadLensesSuccess(lenses)
            logic.actions.setSearch(search)
            logic.actions.setEnabledFilter(enabled)
            logic.actions.setLensTypeFilter(types)
        }).toMatchValues({
            filteredLenses: lenses.filter((l) => expected.includes(l.id)),
        })
    })

    it('hasActiveFilters tracks any active filter', async () => {
        await expectLogic(logic).toMatchValues({ hasActiveFilters: false })

        await expectLogic(logic, () => logic.actions.setSearch('foo')).toMatchValues({ hasActiveFilters: true })
        await expectLogic(logic, () => logic.actions.setSearch('')).toMatchValues({ hasActiveFilters: false })

        await expectLogic(logic, () => logic.actions.setEnabledFilter(['enabled'])).toMatchValues({
            hasActiveFilters: true,
        })
    })

    it('clearFilters resets all filter state', async () => {
        logic.actions.setSearch('foo')
        logic.actions.setEnabledFilter(['enabled'])
        logic.actions.setLensTypeFilter(['monitor'])
        await expectLogic(logic).toMatchValues({ hasActiveFilters: true })

        await expectLogic(logic, () => logic.actions.clearFilters()).toMatchValues({
            search: '',
            enabledFilter: [],
            lensTypeFilter: [],
            hasActiveFilters: false,
        })
    })

    it('toggleLensEnabledSuccess flips the lens row', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadLensesSuccess(lenses)
            logic.actions.toggleLensEnabledSuccess('a')
        }).toMatchValues({
            lenses: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: false })]),
        })
    })
})
