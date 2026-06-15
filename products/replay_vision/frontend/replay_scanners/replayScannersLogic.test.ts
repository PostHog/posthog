import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { makeQuota as makeQuotaFixture } from '../utils/quotaTestUtils'
import {
    buildScannerListParams,
    replayScannersLogic,
    resolveScannerOrderByKey,
    type ScannerOrderKey,
} from './replayScannersLogic'
import { ScannerConfig, ScannerType, ReplayScanner } from './types'

const quotaFixture = makeQuotaFixture({
    monthly_quota: 1000,
    usage_this_month: 100,
    remaining: 900,
    projected_monthly_observations: 500,
})

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
                '/api/projects/:team/vision/scanners/': { results: [], count: 0 },
                '/api/projects/:team/vision/scanners/creators/': { creators: [] },
            },
            patch: {
                '/api/projects/:team/vision/scanners/:id/': () => [200, {}],
            },
            delete: {
                '/api/projects/:team/vision/scanners/:id/': () => [204, null],
            },
        })
        initKeaTests()
        logic = replayScannersLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    const alice = {
        id: 1,
        uuid: '00000000-0000-0000-0000-000000000001',
        first_name: 'Alice',
        last_name: 'Anderson',
        email: 'alice@example.com',
        hedgehog_config: null,
    }
    const bob = {
        id: 2,
        uuid: '00000000-0000-0000-0000-000000000002',
        first_name: 'Bob',
        last_name: 'Brown',
        email: 'bob@example.com',
        hedgehog_config: null,
    }

    const scanners: ReplayScanner[] = [
        makeScanner({ id: 'a', name: 'Confused checkout', scanner_type: 'monitor', enabled: true, created_by: alice }),
        makeScanner({ id: 'b', name: 'Power user behavior', scanner_type: 'classifier', enabled: false }),
        makeScanner({ id: 'c', name: 'Refund summarizer', scanner_type: 'summarizer', enabled: true, created_by: bob }),
    ]

    describe('buildScannerListParams', () => {
        const emptyValues = {
            search: '',
            enabledFilter: [],
            scannerTypeFilter: [],
            createdByFilter: [],
            scannersSort: null,
        }

        it('returns empty params when nothing is set', () => {
            expect(buildScannerListParams({ ...emptyValues })).toEqual({})
        })

        it('passes limit and offset (offset only when > 0)', () => {
            expect(buildScannerListParams({ ...emptyValues }, 50, 0)).toEqual({ limit: 50 })
            expect(buildScannerListParams({ ...emptyValues }, 50, 100)).toEqual({ limit: 50, offset: 100 })
        })

        it('CSV-joins each filter array; trims search', () => {
            const params = buildScannerListParams({
                ...emptyValues,
                search: '   hello   ',
                enabledFilter: ['enabled', 'disabled'],
                scannerTypeFilter: ['monitor', 'classifier'],
                createdByFilter: ['1', '42'],
            })
            expect(params.search).toBe('hello')
            expect(params.enabled).toBe('enabled,disabled')
            expect(params.scanner_type).toBe('monitor,classifier')
            expect(params.created_by).toBe('1,42')
        })

        it('omits an all-whitespace search', () => {
            const params = buildScannerListParams({ ...emptyValues, search: '   ' })
            expect(params.search).toBeUndefined()
        })

        it.each<[ScannerOrderKey, 1 | -1, string]>([
            ['name', 1, 'name'],
            ['created_at', -1, '-created_at'],
            ['sampling_rate', 1, 'sampling_rate'],
            ['created_by', -1, '-created_by'],
        ])('serializes sort %p:%p as %s', (columnKey, order, expected) => {
            const params = buildScannerListParams({
                ...emptyValues,
                scannersSort: { columnKey, order },
            })
            expect(params.order_by).toBe(expected)
        })

        it('drops sort on unknown column key', () => {
            const params = buildScannerListParams({
                ...emptyValues,
                scannersSort: { columnKey: 'unknown_column' as ScannerOrderKey, order: 1 },
            })
            expect(params.order_by).toBeUndefined()
        })
    })

    describe('resolveScannerOrderByKey', () => {
        it.each(['name', 'enabled', 'scanner_type', 'sampling_rate', 'created_by', 'created_at', 'updated_at'])(
            'accepts %s',
            (key) => {
                expect(resolveScannerOrderByKey(key)).toBe(key)
            }
        )

        it('rejects unknown keys', () => {
            expect(resolveScannerOrderByKey('description')).toBeNull()
            expect(resolveScannerOrderByKey('')).toBeNull()
        })
    })

    describe('hasActiveFilters', () => {
        it('tracks any active filter', async () => {
            await expectLogic(logic).toMatchValues({ hasActiveFilters: false })

            await expectLogic(logic, () => logic.actions.setScannersFilters({ search: 'foo' })).toMatchValues({
                hasActiveFilters: true,
            })
            await expectLogic(logic, () => logic.actions.setScannersFilters({ search: '' })).toMatchValues({
                hasActiveFilters: false,
            })

            await expectLogic(logic, () =>
                logic.actions.setScannersFilters({ enabledFilter: ['enabled'] })
            ).toMatchValues({
                hasActiveFilters: true,
            })
            await expectLogic(logic, () => logic.actions.setScannersFilters({ enabledFilter: [] })).toMatchValues({
                hasActiveFilters: false,
            })

            await expectLogic(logic, () => logic.actions.setScannersFilters({ createdByFilter: ['1'] })).toMatchValues({
                hasActiveFilters: true,
            })
        })
    })

    describe('clearFilters', () => {
        it('resets all filter state', async () => {
            logic.actions.setScannersFilters({ search: 'foo' })
            logic.actions.setScannersFilters({ enabledFilter: ['enabled'] })
            logic.actions.setScannersFilters({ scannerTypeFilter: ['monitor'] })
            logic.actions.setScannersFilters({ createdByFilter: ['1'] })
            await expectLogic(logic).toMatchValues({ hasActiveFilters: true })

            await expectLogic(logic, () => logic.actions.clearFilters()).toMatchValues({
                search: '',
                enabledFilter: [],
                scannerTypeFilter: [],
                createdByFilter: [],
                hasActiveFilters: false,
            })
        })
    })

    describe('createdByOptions', () => {
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
                logic.actions.loadCreatorsSuccess([alice, bob])
                logic.actions.setScannersFilters({ createdByFilter: createdBy })
            }).toMatchValues({
                createdByOptions: expected,
            })
        })
    })

    describe('page / sort interactions', () => {
        it('changing a filter resets page to 1', async () => {
            logic.actions.setScannersFilters({ page: 5 })
            expect(logic.values.scannersPage).toBe(5)
            await expectLogic(logic, () => {
                logic.actions.setScannersFilters({ enabledFilter: ['enabled'] })
            }).toMatchValues({ scannersPage: 1 })
        })

        it('changing sort resets page to 1', async () => {
            logic.actions.setScannersFilters({ page: 3 })
            await expectLogic(logic, () => {
                logic.actions.setScannersFilters({ sort: { columnKey: 'name', order: 1 } })
            }).toMatchValues({ scannersPage: 1 })
        })

        it('writes non-default state into the URL', async () => {
            await expectLogic(logic, () => {
                logic.actions.setScannersFilters({ enabledFilter: ['enabled'] })
                logic.actions.setScannersFilters({ page: 2 })
            }).toFinishAllListeners()
            expect(router.values.searchParams.enabled).toBe('enabled')
            expect(String(router.values.searchParams.page)).toBe('2')
        })

        it('omits defaults from the URL', async () => {
            await expectLogic(logic, () => {
                logic.actions.setScannersFilters({ page: 1 })
                logic.actions.setScannersFilters({ sort: { columnKey: 'created_at', order: -1 } })
            }).toFinishAllListeners()
            expect(router.values.searchParams.page).toBeUndefined()
            expect(router.values.searchParams.sort).toBeUndefined()
        })
    })

    describe('delete refresh', () => {
        it('deleteScannerSuccess refetches the page and the creators list', async () => {
            await expectLogic(logic, () => logic.actions.deleteScannerSuccess('a')).toDispatchActions([
                'loadScanners',
                'loadCreators',
            ])
        })
    })

    describe('optimistic toggle', () => {
        it('toggleScannerEnabled optimistically flips the row and marks it in-flight', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadScannersSuccess(scanners, scanners.length)
                logic.actions.toggleScannerEnabled('a')
            }).toMatchValues({
                scanners: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: false })]),
                togglingIds: ['a'],
            })
        })

        it('revertScannerEnabled flips the row back and clears the in-flight id', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadScannersSuccess(scanners, scanners.length)
                logic.actions.toggleScannerEnabled('a')
                logic.actions.revertScannerEnabled('a')
            }).toMatchValues({
                scanners: expect.arrayContaining([expect.objectContaining({ id: 'a', enabled: true })]),
                togglingIds: [],
            })
        })

        it('toggle shifts the quota projection optimistically by the stored estimate', async () => {
            const quotaLogic = visionQuotaLogic()
            quotaLogic.mount()
            quotaLogic.actions.loadQuotaSuccess(quotaFixture)
            logic.actions.loadScannersSuccess(
                [makeScanner({ id: 'a', enabled: true, estimated_monthly_observations: 200 })],
                1
            )

            logic.actions.toggleScannerEnabled('a') // disabling → subtract the stored estimate

            expect(quotaLogic.values.quota?.projected_monthly_observations).toBe(300)
            quotaLogic.unmount()
        })

        it('delete shifts the quota projection optimistically for enabled scanners only', async () => {
            const quotaLogic = visionQuotaLogic()
            quotaLogic.mount()
            quotaLogic.actions.loadQuotaSuccess(quotaFixture)
            logic.actions.loadScannersSuccess(
                [
                    makeScanner({ id: 'a', enabled: true, estimated_monthly_observations: 200 }),
                    makeScanner({ id: 'b', name: 'other', enabled: false, estimated_monthly_observations: 999 }),
                ],
                2
            )

            logic.actions.deleteScanner('b') // disabled — contributes nothing to the sum
            expect(quotaLogic.values.quota?.projected_monthly_observations).toBe(500)

            logic.actions.deleteScanner('a')
            expect(quotaLogic.values.quota?.projected_monthly_observations).toBe(300)
            quotaLogic.unmount()
        })

        it('a failed delete reverts the optimistic projection shift', async () => {
            useMocks({
                // The quota GET must be mocked: `toFinishAllListeners` waits out the quota loader too.
                get: { '/api/projects/:team/vision/quota/': quotaFixture },
                delete: { '/api/projects/:team/vision/scanners/:id/': () => [500, {}] },
            })
            const quotaLogic = visionQuotaLogic()
            quotaLogic.mount()
            quotaLogic.actions.loadQuotaSuccess(quotaFixture)
            logic.actions.loadScannersSuccess(
                [makeScanner({ id: 'a', enabled: true, estimated_monthly_observations: 200 })],
                1
            )

            await expectLogic(logic, () => logic.actions.deleteScanner('a')).toFinishAllListeners()

            expect(quotaLogic.values.quota?.projected_monthly_observations).toBe(500)
            quotaLogic.unmount()
        })
    })

    it('setChartDateRange updates the chart date range', async () => {
        await expectLogic(logic, () => logic.actions.setChartDateRange('-90d', null)).toMatchValues({
            chartDateFrom: '-90d',
            chartDateTo: null,
        })
    })
})
