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
        model: 'gemini-3-flash',
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
                '/api/environments/:team/vision/scanners/': { results: [] },
                '/api/environments/:team/vision/quota/': () => [404, {}],
            },
        })
        initKeaTests()
        logic = replayScannersLogic({ tabId: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    const scanners: ReplayScanner[] = [
        makeScanner({ id: 'a', name: 'Confused checkout', scanner_type: 'monitor', enabled: true }),
        makeScanner({ id: 'b', name: 'Power user behavior', scanner_type: 'classifier', enabled: false }),
        makeScanner({ id: 'c', name: 'Refund summarizer', scanner_type: 'summarizer', enabled: true }),
    ]

    it.each([
        { name: 'no filters returns all', search: '', enabled: [], types: [], expected: ['a', 'b', 'c'] },
        { name: 'search by name', search: 'checkout', enabled: [], types: [], expected: ['a'] },
        { name: 'search by prompt fragment', search: 'struggle', enabled: [], types: [], expected: ['a'] },
        { name: 'enabled filter', search: '', enabled: ['enabled' as const], types: [], expected: ['a', 'c'] },
        { name: 'disabled filter', search: '', enabled: ['disabled' as const], types: [], expected: ['b'] },
        {
            name: 'scanner type filter',
            search: '',
            enabled: [],
            types: ['classifier' as ScannerType, 'summarizer' as ScannerType],
            expected: ['b', 'c'],
        },
        {
            name: 'combined search + enabled',
            search: 'refund',
            enabled: ['enabled' as const],
            types: [],
            expected: ['c'],
        },
    ])('filteredScanners: $name', async ({ search, enabled, types, expected }) => {
        await expectLogic(logic, () => {
            logic.actions.loadScannersSuccess(scanners)
            logic.actions.setSearch(search)
            logic.actions.setEnabledFilter(enabled)
            logic.actions.setScannerTypeFilter(types)
        }).toMatchValues({
            filteredScanners: scanners.filter((l) => expected.includes(l.id)),
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
        logic.actions.setScannerTypeFilter(['monitor'])
        await expectLogic(logic).toMatchValues({ hasActiveFilters: true })

        await expectLogic(logic, () => logic.actions.clearFilters()).toMatchValues({
            search: '',
            enabledFilter: [],
            scannerTypeFilter: [],
            hasActiveFilters: false,
        })
    })

    it('toggleScannerEnabledSuccess flips the scanner row', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadScannersSuccess(scanners)
            logic.actions.toggleScannerEnabledSuccess('a')
        }).toMatchValues({
            scanners: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: false })]),
        })
    })
})
