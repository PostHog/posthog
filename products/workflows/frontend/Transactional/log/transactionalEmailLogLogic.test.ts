import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TransactionalEmailLogEntryApi } from 'products/messaging/frontend/generated/api.schemas'

import { transactionalEmailLogLogic } from './transactionalEmailLogLogic'

const NOW = '2026-03-15T12:00:00.000Z'
const LATER = '2026-03-15T12:05:00.000Z'
const LAST_WEEK = { date_from: '2026-03-08T00:00:00.000Z', date_to: NOW, limit: '50' }

const sends = (count: number): TransactionalEmailLogEntryApi[] =>
    Array.from({ length: count }, (_, i) => ({ message_id: `msg-${i}` }) as TransactionalEmailLogEntryApi)

describe('transactionalEmailLogLogic', () => {
    let logic: ReturnType<typeof transactionalEmailLogLogic.build>
    let requests: Record<string, string>[]
    let response: [number, unknown]

    beforeEach(async () => {
        jest.useFakeTimers({
            now: new Date(NOW),
            doNotFake: ['nextTick', 'queueMicrotask', 'setImmediate', 'setTimeout', 'clearTimeout'],
        })
        requests = []
        response = [200, { results: sends(2), has_more: false }]
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/': ({ request }) => {
                    requests.push(Object.fromEntries(new URL(request.url).searchParams))
                    return response
                },
            },
        })
        initKeaTests()
        router.actions.push('/transactional/log', { tab: 'sends' })
        logic = transactionalEmailLogLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => logic.unmount())

    it('loads the last week of sends on open, and queries each filter change from the first page', async () => {
        expect(requests).toEqual([{ ...LAST_WEEK, offset: '0' }])
        expect(logic.values.emails.map((e) => e.message_id)).toEqual(['msg-0', 'msg-1'])

        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setFilters({ search: '  ada@example' })
        logic.actions.setFilters({ search: '  ada@example.com ', status: 'bounced', workflowId: 'flow-1' })
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.slice(2)).toEqual([
            { ...LAST_WEEK, offset: '0', search: 'ada@example.com', status: 'bounced', workflow_id: 'flow-1' },
        ])
        expect(logic.values.filters.page).toBe(1)
    })

    it.each([
        ['a search of only spaces', { search: '   ' }, false],
        ['a status', { status: 'failed' as const }, true],
        ['an email', { workflowId: 'flow-1' }, true],
        ['a date range', { dateFrom: '-1d' }, false],
    ])('tells whether %s narrows the list', (_, filters, filtered) => {
        logic.actions.setFilters(filters)
        expect(logic.values.isFiltered).toBe(filtered)
    })

    it.each([
        ['-90d', '2026-04-01', '2026-02-13T12:00:00.000Z', NOW],
        ['2026-03-10', '2026-03-12', '2026-03-10T00:00:00.000Z', '2026-03-12T00:00:00.000Z'],
    ])('queries %s to %s within what the log keeps', async (dateFrom, dateTo, date_from, date_to) => {
        logic.actions.setFilters({ dateFrom, dateTo })
        await expectLogic(logic).toFinishAllListeners()
        expect(requests.at(-1)).toEqual({ ...LAST_WEEK, date_from, date_to, offset: '0' })
    })

    it('pages through one fixed window, counts "N+" while more exist, and refresh starts a new window', async () => {
        response = [200, { results: sends(50), has_more: true }]
        logic.actions.loadEmails()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pagination).toMatchObject({ currentPage: 1, entryCount: 51, entryCountIsLowerBound: true })

        jest.setSystemTime(new Date(LATER))
        response = [200, { results: sends(3), has_more: false }]
        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()
        expect(requests.at(-1)).toEqual({ ...LAST_WEEK, offset: '50' })
        expect(logic.values.pagination).toMatchObject({ currentPage: 2, entryCount: 53, entryCountIsLowerBound: false })

        logic.actions.refresh()
        await expectLogic(logic).toFinishAllListeners()
        expect(requests.at(-1)).toEqual({ ...LAST_WEEK, date_to: LATER, offset: '0' })
        expect(logic.values.filters.page).toBe(1)
    })

    it('shows a failed load until a retry succeeds', async () => {
        response = [500, { detail: 'boom' }]
        logic.actions.refresh()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pageFailed).toBe(true)

        response = [200, { results: sends(1), has_more: false }]
        logic.actions.loadEmails()
        expect(logic.values.pageFailed).toBe(false)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.emails.map((e) => e.message_id)).toEqual(['msg-0'])
    })

    it('writes every filter but the search to the URL, keeping params it does not own', async () => {
        logic.actions.setFilters({
            search: 'ada@example.com',
            status: 'bounced',
            workflowId: 'flow-1',
            dateFrom: '-14d',
            dateTo: '2026-03-14',
        })
        logic.actions.setPage(3)
        expect(router.values.searchParams).toEqual({
            tab: 'sends',
            status: 'bounced',
            email: 'flow-1',
            date_from: '-14d',
            date_to: '2026-03-14',
            page: 3,
        })

        logic.actions.setFilters({ status: null, workflowId: null, dateFrom: '-7d', dateTo: null })
        expect(router.values.searchParams).toEqual({ tab: 'sends' })
    })

    it.each([
        ['page=4', '150'],
        ['page=0', '0'],
        ['page=abc', '0'],
    ])('reads filters from a shared link with %s', async (pageParam, offset) => {
        logic.actions.setFilters({ search: 'ada' })
        await expectLogic(logic).toFinishAllListeners()

        router.actions.push(
            `/transactional/log?status=failed&email=flow-2&date_from=-3d&date_to=2026-03-14&${pageParam}`
        )
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.at(-1)).toEqual({
            search: 'ada',
            status: 'failed',
            workflow_id: 'flow-2',
            date_from: '2026-03-12T00:00:00.000Z',
            date_to: '2026-03-14T00:00:00.000Z',
            limit: '50',
            offset,
        })
    })
})
