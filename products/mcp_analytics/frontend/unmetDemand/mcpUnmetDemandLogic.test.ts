import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { MCPUnmetDemandItem } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    UNMET_DEMAND_PAGE_SIZE,
    isUnidentifiedClient,
    mcpUnmetDemandLogic,
    parsePersonProperties,
} from './mcpUnmetDemandLogic'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

type UnmetDemandLogic = ReturnType<typeof mcpUnmetDemandLogic.build>

const report = (intent: string, overrides: Partial<MCPUnmetDemandItem> = {}): MCPUnmetDemandItem => ({
    timestamp: '2026-07-15 00:00:00',
    intent,
    harness: 'Claude Code',
    session_id: 's1',
    distinct_id: 'd1',
    person_properties: '{}',
    ...overrides,
})

describe('unmet demand row helpers', () => {
    // A report with no client identity is common (the SDK only stamps $mcp_client_name on
    // $mcp_initialize), so the table must tell that apart from a named client.
    it.each([
        ['an empty label', '', true],
        ['the backend placeholder', 'Unidentified client', true],
        ['a known harness', 'Claude Code', false],
        ['a self-reported client', 'some-inhouse-agent', false],
    ])('treats %s as unidentified: %s', (_label, harness, expected) => {
        expect(isUnidentifiedClient(harness)).toBe(expected)
    })

    it.each([
        ['a person blob', '{"email":"a@b.com"}', { email: 'a@b.com' }],
        ['an empty blob', '{}', {}],
        ['a missing value', '', {}],
        ['malformed JSON', '{not json', {}],
        ['a non-object', '"a@b.com"', {}],
    ])('parses %s', (_label, raw, expected) => {
        expect(parsePersonProperties(raw)).toEqual(expected)
    })
})

describe('mcpUnmetDemandLogic', () => {
    let logic: UnmetDemandLogic | null = null

    // Mounted per test, not in beforeEach: afterMount fires the first page load, so the
    // response for it has to be queued before the logic exists.
    function mountLogic(): UnmetDemandLogic {
        logic = mcpUnmetDemandLogic()
        logic.mount()
        return logic
    }

    beforeEach(() => {
        initKeaTests()
        mockApi.query.mockResolvedValue({ results: [], has_next: false } as any)
    })

    afterEach(() => {
        logic?.unmount()
        logic = null
        jest.clearAllMocks()
    })

    it('loads the first page over a 30-day window on mount, matching the checklist count', async () => {
        await expectLogic(mountLogic()).toDispatchActions(['loadReports', 'loadReportsSuccess'])

        expect(mockApi.query).toHaveBeenCalledWith(
            expect.objectContaining({
                kind: 'MCPUnmetDemandQuery',
                dateRange: { date_from: '-30d', date_to: null },
                limit: UNMET_DEMAND_PAGE_SIZE,
                offset: 0,
            })
        )
    })

    // A search or a date change is a different result set, so both reset to page one. The term
    // itself goes to the backend, which does the case-insensitive matching.
    it.each<[string, (logic: UnmetDemandLogic) => void, Record<string, unknown>]>([
        ['a search term', (l) => l.actions.setSearch('pdf'), { search: 'pdf', offset: 0 }],
        [
            'a date change',
            (l) => l.actions.setDateFilter('-7d', null),
            { dateRange: { date_from: '-7d', date_to: null }, offset: 0 },
        ],
    ])('reloads from the first page on %s', async (_label, act, expected) => {
        const mounted = mountLogic()
        await expectLogic(mounted).toDispatchActions(['loadReportsSuccess'])
        mockApi.query.mockClear()

        await expectLogic(mounted, () => act(mounted)).toDispatchActions(['loadReports', 'loadReportsSuccess'])

        expect(mockApi.query).toHaveBeenCalledWith(expect.objectContaining(expected))
    })

    it('appends the next page at the current offset and tracks whether more remain', async () => {
        mockApi.query.mockResolvedValueOnce({ results: [report('first ask')], has_next: true } as any)
        const mounted = mountLogic()
        await expectLogic(mounted).toDispatchActions(['loadReportsSuccess'])
        expect(mounted.values.hasNext).toBe(true)

        mockApi.query.mockResolvedValueOnce({ results: [report('second ask')], has_next: false } as any)
        await expectLogic(mounted, () => {
            mounted.actions.loadMoreReports()
        }).toDispatchActions(['loadMoreReportsSuccess'])

        expect(mockApi.query).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 1 }))
        expect(mounted.values.reports.map((r) => r.intent)).toEqual(['first ask', 'second ask'])
        expect(mounted.values.hasNext).toBe(false)
    })

    // Guards the stale-append race: a "Load more" still in flight when the filters change must
    // not splice its page onto the new result set.
    it('discards a page whose query changed while it was in flight', async () => {
        mockApi.query.mockResolvedValueOnce({ results: [report('old ask')], has_next: true } as any)
        const mounted = mountLogic()
        await expectLogic(mounted).toDispatchActions(['loadReportsSuccess'])

        let resolveSlowPage: (value: unknown) => void = () => {}
        mockApi.query.mockImplementationOnce(() => new Promise((resolve) => (resolveSlowPage = resolve)) as any)
        await expectLogic(mounted, () => {
            mounted.actions.loadMoreReports()
        }).toDispatchActions(['loadMoreReports'])

        mockApi.query.mockResolvedValueOnce({ results: [report('new ask')], has_next: false } as any)
        await expectLogic(mounted, () => {
            mounted.actions.setSearch('new')
        }).toDispatchActions(['loadReportsSuccess'])

        resolveSlowPage({ results: [report('stale ask')], has_next: true })
        await expectLogic(mounted).toDispatchActions(['loadMoreReportsSuccess'])

        expect(mounted.values.reports.map((r) => r.intent)).toEqual(['new ask'])
    })
})
