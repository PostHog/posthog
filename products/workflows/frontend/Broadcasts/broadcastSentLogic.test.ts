import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MessageAsset } from '../Workflows/messageAssetsApi'
import { broadcastSendingLogic } from './broadcastSendingLogic'
import { BroadcastSentLogicProps, broadcastSentLogic } from './broadcastSentLogic'

const sends = (prefix: string, count: number): MessageAsset[] =>
    Array.from({ length: count }, (_, i) => ({
        invocation_id: `${prefix}-${i}`,
        action_id: 'email',
        function_id: 'flow-1',
        function_name: 'Broadcast',
        parent_run_id: 'run-1',
        kind: 'email',
        distinct_id: `${prefix}-${i}`,
        person_id: `person-${prefix}-${i}`,
        recipient: `${prefix}-${i}@example.com`,
        subject: 'Hello',
        status: 'sent',
        sent_at: '2026-01-01T00:00:00Z',
    }))

const RECENT_RUN = { id: 'flow-1', parentRunId: 'run-1', runCreatedAt: '2026-11-12T15:49:00Z' }

describe('broadcastSentLogic', () => {
    let requests: { params: Record<string, string | undefined>; resolve: (rows: MessageAsset[]) => void }[]
    let server: { sends: MessageAsset[]; missed: string[][]; queries: string[]; hold: boolean; down: boolean }
    let stillToSend: number

    beforeEach(() => {
        initKeaTests()
        requests = []
        stillToSend = 4
        const otherRun = sends('other', 2).map((send) => ({ ...send, parent_run_id: 'run-2' }))
        server = { sends: [...sends('all', 3), ...otherRun], missed: [], queries: [], hold: false, down: false }
        const answer = (params: Record<string, string | undefined>, rows: MessageAsset[]): Promise<MessageAsset[]> =>
            new Promise((resolve) => {
                requests.push({ params, resolve })
                if (!server.hold) {
                    resolve(rows)
                }
            })
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/assets/': async ({ request, params: { id } }) => {
                    const params = Object.fromEntries(new URL(request.url).searchParams)
                    const search = params.search?.trim()
                    const offset = Number(params.offset)
                    const matches = server.sends.filter(
                        (send) =>
                            send.function_id === id &&
                            send.parent_run_id === params.parent_run_id &&
                            (!search || send.recipient.includes(search))
                    )
                    const rows = await answer(params, matches.slice(offset, offset + Number(params.limit)))
                    return server.down || search === '' || Number(params.limit) > 500 ? [400, {}] : [200, rows]
                },
                '/api/projects/:team_id/hog_flows/:id/': ({ params }) => [200, { id: params.id }],
                '/api/projects/:team_id/hog_flows/:id/in_flight/': () => [200, { count: stillToSend }],
            },
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const query = JSON.stringify(await request.json())
                    const search = /distinct_id ILIKE '%([^%']*)%'/.exec(query)?.[1]
                    server.queries.push(query)
                    await answer({ search }, [])
                    const scoped = query.includes("function_id = 'flow-1'") && query.includes("parent_run_id = 'run-1'")
                    const rows = server.missed.filter((row) => scoped && (!search || row[3].includes(search)))
                    const counts = rows.length ? [['failed', rows.length]] : []
                    return server.down
                        ? [500, {}]
                        : [200, { results: query.includes('GROUP BY status') ? counts : rows }]
                },
            },
        })
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        jest.useRealTimers()
    })

    const mountRun = (props: Partial<BroadcastSentLogicProps> = {}): ReturnType<typeof broadcastSentLogic.build> => {
        const logic = broadcastSentLogic({ ...RECENT_RUN, ...props })
        logic.mount()
        return logic
    }
    const settle = async (ms = 0): Promise<void> => {
        for (let tick = 0; tick < 5; tick++) {
            await jest.advanceTimersByTimeAsync(tick ? 0 : ms)
        }
    }
    const shown = (logic: ReturnType<typeof broadcastSentLogic.build>): string[] =>
        logic.values.sends.map((send) => send.distinct_id)
    const statusReads = (): number => server.queries.filter((query) => query.includes('GROUP BY status')).length

    it('keeps the new search results when a stale load-more re-enables the button', async () => {
        jest.useFakeTimers()
        try {
            server.sends = [...sends('all', 1000), ...sends('ada', 1)]
            server.hold = true
            const logic = broadcastSentLogic({ id: 'flow-1', parentRunId: 'run-1', runCreatedAt: null })
            logic.mount()

            logic.actions.loadSends()
            await jest.advanceTimersByTimeAsync(0)
            requests[0].resolve(sends('all', 500))
            await jest.advanceTimersByTimeAsync(0)

            logic.actions.loadMoreSends()
            logic.actions.setRecipientSearch('ada')
            await jest.advanceTimersByTimeAsync(300)
            requests[1].resolve(sends('all-page-2', 500))
            await jest.advanceTimersByTimeAsync(0)

            logic.actions.loadMoreSends()
            const searchRequest = requests.find((request) => request.params.search === 'ada')
            searchRequest?.resolve(sends('ada', 1))
            await jest.advanceTimersByTimeAsync(0)
            requests
                .filter((request) => request !== searchRequest)
                .forEach((request) => request.resolve(sends('stale', 500)))
            await jest.advanceTimersByTimeAsync(0)

            expect(logic.values.sends.map((send) => send.invocation_id)).toEqual(['ada-0'])
        } finally {
            jest.useRealTimers()
        }
    })

    it('sends a search of only spaces as no search', async () => {
        jest.useFakeTimers()
        try {
            const logic = broadcastSentLogic({ id: 'flow-1', parentRunId: 'run-1', runCreatedAt: null })
            logic.mount()

            logic.actions.setRecipientSearch('   ')
            await settle(300)

            expect(requests).toHaveLength(1)
            expect(requests[0].params.search).toBeUndefined()
            expect(logic.values).toMatchObject({ sendsFailed: false, recipientCount: 3 })
        } finally {
            jest.useRealTimers()
        }
    })

    it('loads the full list at once when a search with no matches is cleared', async () => {
        jest.useFakeTimers()
        try {
            const logic = broadcastSentLogic({ id: 'flow-1', parentRunId: 'run-1', runCreatedAt: null })
            logic.mount()

            logic.actions.setRecipientSearch('nobody')
            await settle(300)
            expect(logic.values.recipientCount).toBe(0)

            logic.actions.setRecipientSearch('')

            expect(logic.values.sendsLoading).toBe(true)
            await settle()
            expect(requests).toHaveLength(2)
            expect(requests[1].params.search).toBeUndefined()
            expect(logic.values.recipientCount).toBe(3)
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([
        ['on the 29th UTC day after the run started', '2026-01-30T23:59:00Z', false],
        ['from UTC midnight on the 30th day, before 30 full days pass', '2026-01-31T00:00:00Z', true],
    ])('marks a late-day run as past retention %s', (_, now, expected) => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date(now))
        try {
            const logic = broadcastSentLogic({
                id: 'flow-1',
                parentRunId: 'run-1',
                runCreatedAt: '2026-01-01T23:00:00Z',
            })
            logic.mount()

            expect(logic.values.runPastRetention).toBe(expected)
        } finally {
            jest.useRealTimers()
        }
    })

    describe('with the clock at the run', () => {
        beforeEach(() => {
            jest.useFakeTimers({ now: new Date('2026-11-12T16:00:00Z') })
        })

        it.each([
            { case: 'a full page', count: 500, hasMore: true },
            { case: 'a short page', count: 3, hasMore: false },
        ])('lists the first page of this run only, given $case', async ({ count, hasMore }) => {
            server.sends = [...server.sends.slice(3), ...sends('all', count)]
            const logic = mountRun()

            logic.actions.loadSends()
            await settle()

            expect(requests.map((request) => request.params)).toEqual([
                { parent_run_id: 'run-1', limit: '500', offset: '0' },
            ])
            expect(logic.values).toMatchObject({ recipientCount: count, hasMoreRecipients: hasMore })
            expect(shown(logic)[count - 1]).toBe(`all-${count - 1}`)
        })

        it.each([
            { case: 'an unsaved broadcast', props: { id: 'new' }, sendReads: 0 },
            { case: 'no run', props: { parentRunId: null }, sendReads: 0 },
            { case: 'a run with no start time', props: { runCreatedAt: null }, sendReads: 1 },
        ])('reads only what it can scope to the run, given $case', async ({ props, sendReads }) => {
            const logic = mountRun(props)

            logic.actions.loadSends()
            logic.actions.loadNotSent()
            await settle()

            expect([requests.length, server.queries.length]).toEqual([sendReads, 0])
            expect(logic.values.notSent).toEqual({ rows: [], counts: { failed: 0, skipped: 0, canceled: 0 } })
        })

        it('appends the next page of the same search once, skipping people pushed onto it by new sends', async () => {
            server.sends = [...sends('all', 600), ...sends('ada', 1)]
            const logic = mountRun()
            logic.actions.setRecipientSearch('all')
            await settle(300)

            server.sends.unshift(...sends('all-new', 2))
            logic.actions.loadMoreSends()
            await settle()
            logic.actions.loadMoreSends()
            await settle()

            expect(requests.map((request) => request.params.offset)).toEqual(['0', '500', '602'])
            expect(shown(logic)).toEqual(sends('all', 600).map((send) => send.distinct_id))
            expect(logic.values.hasMoreRecipients).toBe(false)
        })

        it('drops a next page that lands after a new search', async () => {
            server.sends = sends('all', 600)
            const logic = mountRun()
            logic.actions.loadSends()
            await settle()

            server.hold = true
            logic.actions.loadMoreSends()
            logic.actions.setRecipientSearch('all-1')
            await settle(300)
            requests[2].resolve(sends('all-1', 1))
            await settle()
            requests[1].resolve(sends('all', 600).slice(500))
            await settle()

            expect(shown(logic)).toEqual(['all-1-0'])
        })

        it('shows the picked send until the list reloads', async () => {
            const logic = mountRun()
            logic.actions.loadSends()
            await settle()

            logic.actions.selectInvocation('all-1')
            expect(logic.values.selectedSend?.recipient).toBe('all-1@example.com')
            logic.actions.loadSends()
            await settle()

            expect(logic.values.selectedSend).toBeNull()
        })

        it('flags failed reads, opens on the sent list, and clears both flags on a retry', async () => {
            silenceKeaLoadersErrors()
            server.down = true
            server.missed = [['inv-ada', 'failed', 'Mailbox unavailable.', 'ada', 'person-ada']]
            const logic = mountRun()
            logic.actions.loadSends()
            logic.actions.loadNotSent()
            await settle()
            expect(logic.values).toMatchObject({ sendsFailed: true, notSentFailed: true, runView: 'sent' })

            server.down = false
            logic.actions.loadSends()
            logic.actions.loadNotSent()
            await settle()

            expect(logic.values).toMatchObject({ sendsFailed: false, notSentFailed: false, notSentCount: 1 })
        })

        it('keeps the full list when an abandoned search fails after it', async () => {
            silenceKeaLoadersErrors()
            server.hold = true
            const logic = mountRun()
            logic.actions.setRecipientSearch('ada')
            await settle(300)
            logic.actions.setRecipientSearch('')
            await settle()

            requests[1].resolve(sends('all', 3))
            await settle()
            server.down = true
            requests[0].resolve([])
            await settle()

            expect(logic.values).toMatchObject({ sendsFailed: false, recipientCount: 3 })
        })

        it('searches the missed people once typing pauses, and drops an older answer', async () => {
            server.missed = [
                ['inv-ada', 'failed', 'Mailbox unavailable.', 'ada', 'person-ada'],
                ['inv-bo', 'failed', 'Bounced.', 'bo', 'person-bo'],
            ]
            server.hold = true
            const logic = mountRun()
            logic.actions.setNotSentSearch('  ad ')
            await settle(299)
            expect(requests).toHaveLength(0)
            await settle(1)
            logic.actions.setNotSentSearch('bo')
            await settle(300)

            expect(requests.map((request) => request.params.search ?? '').sort()).toEqual(['', '', 'ad', 'bo'])
            requests.slice(2).forEach((request) => request.resolve([]))
            await settle()
            requests.slice(0, 2).forEach((request) => request.resolve([]))
            await settle()
            expect(logic.values.notSent?.rows.map((row) => row.distinctId)).toEqual(['bo'])
            expect(logic.values.notSentCount).toBe(2)

            logic.actions.setNotSentSearch('')
            await settle()
            expect(requests).toHaveLength(6)
        })

        it('re-reads who was missed every 30 seconds until nothing is left to send', async () => {
            const logic = mountRun()
            const sending = broadcastSendingLogic({ id: 'flow-1' })
            sending.mount()
            logic.actions.watchNotSent(false)
            await settle(29_999)
            expect(statusReads()).toBe(1)
            await settle(1)
            expect(statusReads()).toBe(2)

            stillToSend = 0
            sending.actions.loadInFlight()
            await settle(120_000)

            expect(statusReads()).toBe(3)
            sending.unmount()
        })

        it.each([
            { case: 'the run finishes', finished: true, reads: 2 },
            { case: 'the run closes', finished: false, reads: 1 },
        ])('stops re-reading when $case', async ({ finished, reads }) => {
            const logic = mountRun()
            logic.actions.watchNotSent(false)
            await settle()

            if (finished) {
                logic.actions.watchNotSent(true)
            } else {
                logic.unmount()
            }
            await settle(90_000)

            expect(statusReads()).toBe(reads)
        })
    })
})
