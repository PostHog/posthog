import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
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
            severity_counts: { error: 3 },
            match_regex: '^\\s*User\\s+\\S+\\s+not\\s+found\\s*$',
            match_literal: 'User',
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

    it('viewMatchingLogs writes a visible message filter and switches to the Logs view', async () => {
        // The pivot's contract: the predicate must land in the shared, user-visible filterGroup
        // (removable like any filter, never hidden state) and the viewer must leave Patterns mode.
        const configLogic = logsViewerConfigLogic({ id: ID })
        configLogic.mount()
        configLogic.actions.setViewMode('patterns')
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPatternsSuccess'])

        logic.actions.viewMatchingLogs(RESPONSE.patterns[0])

        const inner = filtersLogic.values.filters.filterGroup.values[0] as UniversalFiltersGroup
        expect(inner.values).toContainEqual(
            expect.objectContaining({
                key: 'message',
                operator: PropertyOperator.Regex,
                type: PropertyFilterType.Log,
                value: RESPONSE.patterns[0].match_regex,
            })
        )
        // The pattern's sample was unambiguous (one service, one severity), so the pivot also
        // scopes by both — service_name and severity prune the scan the body regex can't.
        expect(filtersLogic.values.filters.serviceNames).toEqual(['auth'])
        expect(filtersLogic.values.filters.severityLevels).toEqual(['error'])
        expect(configLogic.values.viewMode).toBe('logs')
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
