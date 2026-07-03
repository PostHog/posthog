import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logsPatternsCreate } from 'products/logs/frontend/generated/api'
import type { _LogsPatternsResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { logsPatternsLogic } from './logsPatternsLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsPatternsCreate: jest.fn(),
}))

const mockCreate = logsPatternsCreate as jest.MockedFunction<typeof logsPatternsCreate>

const ID = 'test-viewer'

const RESPONSE: _LogsPatternsResponseApi = {
    patterns: [
        {
            pattern: 'User <*> not found',
            count: 3,
            estimated_count: 3,
            volume_share_pct: 75,
            error_count: 3,
            estimated_error_count: 3,
            first_seen: '2026-06-23T12:00:00+00:00',
            last_seen: '2026-06-23T12:05:00+00:00',
            examples: [],
            services: ['auth'],
            sparkline: [1, 2],
        },
    ],
    scanned_count: 3,
    total_count: 3,
    sampled: false,
    sample_coverage_pct: 100,
    sparkline_buckets: [
        { start: '2026-06-23T12:00:00+00:00', end: '2026-06-23T12:30:00+00:00' },
        { start: '2026-06-23T12:30:00+00:00', end: '2026-06-23T13:00:00+00:00' },
    ],
}

describe('logsPatternsLogic', () => {
    let logic: ReturnType<typeof logsPatternsLogic.build>
    let filtersLogic: ReturnType<typeof logsViewerFiltersLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockCreate.mockResolvedValue(RESPONSE)
        filtersLogic = logsViewerFiltersLogic({ id: ID })
        filtersLogic.mount()
        logic = logsPatternsLogic({ id: ID })
    })

    it('loads patterns on mount from the shared viewer filters', async () => {
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadPatterns', 'loadPatternsSuccess'])
            .toMatchValues({ patterns: RESPONSE.patterns })

        expect(mockCreate).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                query: expect.objectContaining({ severityLevels: [], serviceNames: [] }),
            })
        )
    })

    it('surfaces a load failure as patternsError and clears it on the next success', async () => {
        // A failed mine (e.g. sampling query over budget) must not render as "no patterns".
        mockCreate.mockRejectedValueOnce(new Error('estimated query execution time is too long'))
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPatterns', 'loadPatternsFailure'])
        expect(logic.values.patternsError).toBeTruthy()

        await expectLogic(logic, () => {
            logic.actions.loadPatterns()
        }).toDispatchActions(['loadPatternsSuccess'])
        expect(logic.values.patternsError).toBeNull()
    })

    it('reloads when a shared filter changes', async () => {
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])
        mockCreate.mockClear()

        await expectLogic(logic, () => {
            filtersLogic.actions.setSeverityLevels(['error'])
        }).toDispatchActions(['setSeverityLevels', 'loadPatterns', 'loadPatternsSuccess'])

        expect(mockCreate).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ query: expect.objectContaining({ severityLevels: ['error'] }) })
        )
    })

    // The label format flips on a >= 24h window threshold (time-of-day vs date-prefixed) and
    // early-returns on empty buckets — none of the above tests read `sparklineLabels`, so a
    // flipped threshold or a broken dayjs format would otherwise go undetected.
    const labelCases: [string, { start: string; end: string }[], string[]][] = [
        ['empty buckets yield no labels', [], []],
        [
            'a sub-day window uses time-of-day labels',
            [
                { start: '2026-06-23T12:00:00+00:00', end: '2026-06-23T12:30:00+00:00' },
                { start: '2026-06-23T12:30:00+00:00', end: '2026-06-23T13:00:00+00:00' },
            ],
            ['12:00 – 12:30', '12:30 – 13:00'],
        ],
        [
            'a multi-day window prefixes the date',
            [
                { start: '2026-06-23T00:00:00+00:00', end: '2026-06-24T00:00:00+00:00' },
                { start: '2026-06-24T00:00:00+00:00', end: '2026-06-25T00:00:00+00:00' },
            ],
            ['Jun 23 00:00 – Jun 24 00:00', 'Jun 24 00:00 – Jun 25 00:00'],
        ],
    ]
    it.each(labelCases)('builds sparkline labels: %s', async (_name, sparkline_buckets, expected) => {
        mockCreate.mockResolvedValue({ ...RESPONSE, sparkline_buckets })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])
        expect(logic.values.sparklineLabels).toEqual(expected)
    })

    it('scopes mining to the embedding viewer pinned filters', async () => {
        // A scoped embedded viewer (e.g. person/trace logs) pins a filter so Patterns mode
        // can't mine project-wide logs — assert it reaches the query via `queryFilterGroup`.
        const pinnedFilters: UniversalFiltersGroup = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: 'distinct_id',
                    value: ['user-123'],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.LogAttribute,
                },
            ],
        }
        const scopedFiltersLogic = logsViewerFiltersLogic({ id: 'scoped-viewer', pinnedFilters })
        scopedFiltersLogic.mount()
        const scopedLogic = logsPatternsLogic({ id: 'scoped-viewer' })
        scopedLogic.mount()

        await expectLogic(scopedLogic).toDispatchActions(['loadPatternsSuccess'])

        expect(mockCreate).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                query: expect.objectContaining({
                    filterGroup: expect.objectContaining({
                        values: [expect.objectContaining({ values: pinnedFilters.values })],
                    }),
                }),
            })
        )
    })
})
