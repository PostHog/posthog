import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayScannersLogic } from './replayScannersLogic'
import { ScannerConfig, ScannerType, ReplayScanner } from './types'

function defaultConfigForType(scannerType: ScannerType): ScannerConfig {
    if (scannerType === 'summarizer') {
        return { prompt: 'Summarize this session.', length: 'medium' }
    }
    if (scannerType === 'classifier') {
        return { prompt: 'Tag this session.', tags: [], multi_label: true }
    }
    if (scannerType === 'scorer') {
        return { prompt: 'Score this session.', scale: { min: 0, max: 10 } }
    }
    return { prompt: 'Did the user struggle?' }
}

function makeScanner(overrides: Partial<ReplayScanner> = {}): ReplayScanner {
    const scannerType: ScannerType = overrides.scanner_type ?? 'monitor'
    const base = {
        id: 'scanner-1',
        name: 'Confused checkout',
        description: '',
        enabled: true,
        sampling_rate: 0.1,
        query: null,
        provider: 'google',
        model: 'gemini-3-flash-preview',
        emits_signals: false,
        scanner_version: 1,
        last_swept_at: '2026-05-12T00:00:00Z',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
        created_by: null,
        scanner_type: scannerType,
        scanner_config: defaultConfigForType(scannerType),
    }
    return { ...base, ...overrides } as ReplayScanner
}

describe('replayScannersLogic', () => {
    let logic: ReturnType<typeof replayScannersLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': { results: [] },
            },
            patch: {
                '/api/projects/:team/vision/scanners/:id/': () => [200, {}],
            },
        })
        initKeaTests()
        logic = replayScannersLogic({ tabId: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    const alice = { id: 1, first_name: 'Alice', last_name: 'Anderson', email: 'alice@example.com' }
    const bob = { id: 2, first_name: 'Bob', last_name: 'Brown', email: 'bob@example.com' }

    const scanners: ReplayScanner[] = [
        makeScanner({ id: 'a', name: 'Confused checkout', scanner_type: 'monitor', enabled: true, created_by: alice }),
        makeScanner({ id: 'b', name: 'Power user behavior', scanner_type: 'classifier', enabled: false }),
        makeScanner({ id: 'c', name: 'Refund summarizer', scanner_type: 'summarizer', enabled: true, created_by: bob }),
    ]

    it.each([
        {
            name: 'no filters returns all',
            search: '',
            enabled: [],
            types: [],
            createdBy: [],
            expected: ['a', 'b', 'c'],
        },
        { name: 'search by name', search: 'checkout', enabled: [], types: [], createdBy: [], expected: ['a'] },
        {
            name: 'search by prompt fragment',
            search: 'struggle',
            enabled: [],
            types: [],
            createdBy: [],
            expected: ['a'],
        },
        {
            name: 'enabled filter',
            search: '',
            enabled: ['enabled' as const],
            types: [],
            createdBy: [],
            expected: ['a', 'c'],
        },
        {
            name: 'disabled filter',
            search: '',
            enabled: ['disabled' as const],
            types: [],
            createdBy: [],
            expected: ['b'],
        },
        {
            name: 'scanner type filter',
            search: '',
            enabled: [],
            types: ['classifier' as ScannerType, 'summarizer' as ScannerType],
            createdBy: [],
            expected: ['b', 'c'],
        },
        {
            name: 'combined search + enabled',
            search: 'refund',
            enabled: ['enabled' as const],
            types: [],
            createdBy: [],
            expected: ['c'],
        },
        { name: 'created by single user', search: '', enabled: [], types: [], createdBy: ['1'], expected: ['a'] },
        {
            name: 'created by multiple users excludes null creator',
            search: '',
            enabled: [],
            types: [],
            createdBy: ['1', '2'],
            expected: ['a', 'c'],
        },
        {
            name: 'created by unknown id matches nothing',
            search: '',
            enabled: [],
            types: [],
            createdBy: ['999'],
            expected: [],
        },
    ])('filteredScanners: $name', async ({ search, enabled, types, createdBy, expected }) => {
        await expectLogic(logic, () => {
            logic.actions.loadScannersSuccess(scanners)
            logic.actions.setSearch(search)
            logic.actions.setEnabledFilter(enabled)
            logic.actions.setScannerTypeFilter(types)
            logic.actions.setCreatedByFilter(createdBy)
        }).toMatchValues({
            filteredScanners: scanners.filter((l) => expected.includes(l.id)),
        })
    })

    it.each([
        {
            name: 'distinct creators sorted by label, null creators excluded',
            createdBy: [],
            expected: [
                { value: '1', label: 'Alice Anderson' },
                { value: '2', label: 'Bob Brown' },
            ],
        },
        {
            name: 'selected-but-unloaded id is surfaced so it stays untickable',
            createdBy: ['999'],
            expected: [
                { value: '1', label: 'Alice Anderson' },
                { value: '2', label: 'Bob Brown' },
                { value: '999', label: 'User 999' },
            ],
        },
    ])('createdByOptions: $name', async ({ createdBy, expected }) => {
        await expectLogic(logic, () => {
            logic.actions.loadScannersSuccess(scanners)
            logic.actions.setCreatedByFilter(createdBy)
        }).toMatchValues({
            createdByOptions: expected,
        })
    })

    it('hasActiveFilters tracks any active filter', async () => {
        await expectLogic(logic).toMatchValues({ hasActiveFilters: false })

        await expectLogic(logic, () => logic.actions.setSearch('foo')).toMatchValues({ hasActiveFilters: true })
        await expectLogic(logic, () => logic.actions.setSearch('')).toMatchValues({ hasActiveFilters: false })

        await expectLogic(logic, () => logic.actions.setEnabledFilter(['enabled'])).toMatchValues({
            hasActiveFilters: true,
        })
        await expectLogic(logic, () => logic.actions.setEnabledFilter([])).toMatchValues({ hasActiveFilters: false })

        await expectLogic(logic, () => logic.actions.setCreatedByFilter(['1'])).toMatchValues({
            hasActiveFilters: true,
        })
    })

    it('clearFilters resets all filter state', async () => {
        logic.actions.setSearch('foo')
        logic.actions.setEnabledFilter(['enabled'])
        logic.actions.setScannerTypeFilter(['monitor'])
        logic.actions.setCreatedByFilter(['1'])
        await expectLogic(logic).toMatchValues({ hasActiveFilters: true })

        await expectLogic(logic, () => logic.actions.clearFilters()).toMatchValues({
            search: '',
            enabledFilter: [],
            scannerTypeFilter: [],
            createdByFilter: [],
            hasActiveFilters: false,
        })
    })

    it('toggleScannerEnabled optimistically flips the row and marks it in-flight', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadScannersSuccess(scanners)
            logic.actions.toggleScannerEnabled('a')
        }).toMatchValues({
            scanners: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: false })]),
            togglingIds: ['a'],
        })
    })

    it('revertScannerEnabled flips the row back and clears the in-flight id', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadScannersSuccess(scanners)
            logic.actions.toggleScannerEnabled('a')
            logic.actions.revertScannerEnabled('a')
        }).toMatchValues({
            scanners: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: true })]),
            togglingIds: [],
        })
    })

    it('setChartDateRange updates the chart date range', async () => {
        await expectLogic(logic, () => logic.actions.setChartDateRange('-90d', null)).toMatchValues({
            chartDateFrom: '-90d',
            chartDateTo: null,
        })
    })
})
