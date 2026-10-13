import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { MCPMissingCapabilitiesItem } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    MISSING_CAPABILITIES_PAGE_SIZE,
    isUnidentifiedClient,
    mcpMissingCapabilitiesLogic,
    parsePersonProperties,
} from './mcpMissingCapabilitiesLogic'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

type MissingCapabilitiesLogic = ReturnType<typeof mcpMissingCapabilitiesLogic.build>

const report = (intent: string, overrides: Partial<MCPMissingCapabilitiesItem> = {}): MCPMissingCapabilitiesItem => ({
    timestamp: '2026-07-15 00:00:00',
    intent,
    harness: 'Claude Code',
    session_id: 's1',
    distinct_id: 'd1',
    person_properties: '{}',
    ...overrides,
})

describe('mcpMissingCapabilitiesLogic', () => {
    describe('row helpers', () => {
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

    let logic: MissingCapabilitiesLogic | null = null

    function mountLogic(): MissingCapabilitiesLogic {
        logic = mcpMissingCapabilitiesLogic()
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
        resumeKeaLoadersErrors()
        jest.clearAllMocks()
    })

    it('loads the first page over a 30-day window on mount, matching the checklist count', async () => {
        await expectLogic(mountLogic()).toDispatchActions(['loadReports', 'loadReportsSuccess'])

        expect(mockApi.query).toHaveBeenCalledWith(
            expect.objectContaining({
                kind: 'MCPMissingCapabilitiesQuery',
                dateRange: { date_from: '-30d', date_to: null },
                limit: MISSING_CAPABILITIES_PAGE_SIZE,
                offset: 0,
            })
        )
    })

    it.each<[string, (logic: MissingCapabilitiesLogic) => void, Record<string, unknown>]>([
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

    it('keeps a load failure distinct from an empty result and clears it on retry', async () => {
        silenceKeaLoadersErrors()
        mockApi.query.mockRejectedValueOnce(new Error('query failed'))

        const mounted = mountLogic()
        await expectLogic(mounted).toDispatchActions(['loadReportsFailure'])
        expect(mounted.values.reportsError).toBe('query failed')

        mockApi.query.mockResolvedValueOnce({ results: [], has_next: false } as any)
        await expectLogic(mounted, () => mounted.actions.loadReports()).toDispatchActions(['loadReportsSuccess'])
        expect(mounted.values.reportsError).toBeNull()
    })

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
