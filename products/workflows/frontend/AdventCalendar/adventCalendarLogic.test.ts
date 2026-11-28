import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import type { Mocks } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { workflowsSetupLogic } from '../emptyState/workflowsSetupLogic'
import { adventCalendarLogic } from './adventCalendarLogic'
import { ADVENT_QUESTIONS } from './adventContent'

const KEY = 'workflows-advent-calendar-progress'
const TICKETS_KEY = 'workflows-advent-calendar-tickets'
const PENDING_KEY = 'workflows-advent-calendar-pending-tickets'
const UUID = '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01'
const CALENDAR_API = '/api/projects/:team_id/workflow_advent_calendar'

type Reply = number | 'network error'

function replyWith(reply: Reply, body: unknown): Response | [number, unknown] {
    return reply === 'network error' ? Response.error() : [reply, body]
}

const DAY_TWO_ANSWERED = {
    day: 2,
    answer: 'tim',
    shares: [
        { option: 'james', share: 38 },
        { option: 'tim', share: 62 },
    ],
}

function resultsOf(...questions: object[]): { questions: object[] } {
    return { questions }
}

function calendarApi(
    replies: {
        answer?: Reply
        results?: Reply
        open?: Reply
        openedAt?: (day: number) => string
        storedOffset?: number | null
        openHeld?: Promise<void>
    } = {},
    results = resultsOf(DAY_TWO_ANSWERED),
    resultsHeld: Promise<void> = Promise.resolve()
): { mocks: Mocks; answers: unknown[]; opens: unknown[]; reads: number[] } {
    const answers: unknown[] = []
    const opens: unknown[] = []
    const reads: number[] = []
    const mocks: Mocks = {
        get: {
            [`${CALENDAR_API}/results/`]: async () => {
                reads.push(reads.length + 1)
                await resultsHeld
                return replyWith(replies.results ?? 200, results)
            },
        },
        post: {
            [`${CALENDAR_API}/answer/`]: async ({ request }) => {
                answers.push(await request.json())
                return replyWith(replies.answer ?? 200, results)
            },
            [`${CALENDAR_API}/open/`]: async ({ request }) => {
                const open = (await request.json()) as { day: number; utc_offset_minutes: number }
                opens.push(open)
                await replies.openHeld
                const openedAt = replies.openedAt?.(open.day) ?? '2026-12-03T09:00:00Z'
                const storedOffset = replies.storedOffset === undefined ? open.utc_offset_minutes : replies.storedOffset
                return replyWith(replies.open ?? 200, {
                    day: open.day,
                    opened_at: openedAt,
                    ...(storedOffset === null ? {} : { utc_offset_minutes: storedOffset }),
                })
            },
        },
    }
    return { mocks, answers, opens, reads }
}

function signIn(user: Partial<UserType>): void {
    userLogic.actions.loadUserSuccess({ ...userLogic.values.user, ...user } as UserType)
}

function doorOf(
    logic: ReturnType<typeof adventCalendarLogic.build>,
    id: string
): { status: string; reward: string | null } | null {
    const door = logic.values.graph.doors.find((candidate) => candidate.id === id)
    return door ? { status: door.status, reward: door.reward?.name ?? null } : null
}

describe('adventCalendarLogic', () => {
    let logic: ReturnType<typeof adventCalendarLogic.build>
    let capture: jest.SpyInstance
    let sent: [string, unknown][]

    beforeEach(async () => {
        jest.useFakeTimers({ now: new Date(2026, 11, 3, 9, 0), advanceTimers: true })
        window.localStorage.clear()
        sent = []
        capture = jest.spyOn(posthog, 'capture').mockImplementation((event: string, properties?: unknown) => {
            sent.push([event, properties])
            return undefined
        })
        initKeaTests()
        await expectLogic(userLogic).toFinishAllListeners()
        signIn({ uuid: UUID, is_staff: false })
        logic = adventCalendarLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        capture.mockRestore()
        jest.useRealTimers()
    })

    it.each<[string, number[], boolean, boolean | null]>([
        ['nothing has looked for workflows yet', [], false, null],
        ['the Workflows page found none', [0], true, false],
        ['the Workflows page found some', [1], true, true],
        ['an earlier visit to the Workflows page found some', [1], false, true],
        ['the Workflows page found none after an earlier visit found some', [1, 0], true, null],
    ])('reports the view, with whether the project has workflows, when %s', async (_, counts, open, hasWorkflows) => {
        logic.unmount()
        capture.mockClear()
        for (const [visit, count] of counts.entries()) {
            useMocks({
                get: {
                    '/api/projects/:team_id/hog_flows/': {
                        count,
                        results: count ? [{ id: 'workflow-1', name: 'Welcome series' }] : [],
                        next: null,
                        previous: null,
                    },
                },
            })
            const setup = workflowsSetupLogic()
            setup.mount()
            await expectLogic(setup).toFinishAllListeners()
            if (!open || visit < counts.length - 1) {
                setup.unmount()
            }
        }

        logic = adventCalendarLogic()
        logic.mount()

        expect(capture).toHaveBeenCalledWith('workflows advent calendar viewed', { has_workflows: hasWorkflows })
    })

    it('opens the door of the day and keeps it open after a reload', () => {
        logic.actions.activateDoor('door-1')

        expect(doorOf(logic, 'door-1')?.status).toBe('open')
        expect(sent).toContainEqual(['workflows advent door opened', { day: 1, on_time: false }])

        logic.unmount()
        logic = adventCalendarLogic()
        logic.mount()

        expect(doorOf(logic, 'door-1')?.status).toBe('open')
        expect(logic.values.openCount).toBe(1)
    })

    it.each<Reply>([200, 500, 'network error'])(
        'sends each opened door to the server once and keeps it open when it replies %s',
        async (reply) => {
            const api = calendarApi({ open: reply })
            useMocks(api.mocks)
            const offset = 0 - new Date().getTimezoneOffset()

            logic.actions.activateDoor('door-1')
            logic.actions.finishReveal()
            logic.actions.activateDoor('door-1')
            logic.actions.answerDoor('door-2', 'tim')
            await waitFor(() => expect(api.opens).toHaveLength(2))

            const hoggyOne = logic.values.graph.doors.find((door) => door.id === 'door-1')?.reward?.id
            expect(hoggyOne).toMatch(/^[a-z0-9-]+$/)
            expect(api.opens).toHaveLength(2)
            expect(api.opens).toEqual(
                expect.arrayContaining([
                    { day: 1, hoggy: hoggyOne, utc_offset_minutes: offset },
                    { day: 2, hoggy: 'tim', utc_offset_minutes: offset },
                ])
            )
            expect(doorOf(logic, 'door-1')?.status).toBe('open')
        }
    )

    it('earns a ticket only for the door opened on its own day, and counts it once the ticket lands', () => {
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', 'james')
        logic.actions.finishReveal()

        expect(logic.values.tickets).toBe(0)
        expect(logic.values.ticketFlight).toBeNull()

        logic.actions.activateDoor('door-3-upper')

        expect(logic.values.ticketDays).toEqual([3])
        expect(logic.values.ticketFlight).toBe(3)
        expect(logic.values.ticketsShown).toBe(0)

        logic.actions.finishReveal()
        logic.actions.landTicket()

        expect(logic.values.ticketFlight).toBeNull()
        expect(logic.values.ticketsShown).toBe(1)
    })

    it.each<[string, Reply, (day: number) => string, number | null | undefined, number[]]>([
        ['first opened each door on its day', 200, (day) => `2026-12-0${day}T12:00:00Z`, undefined, [1, 2, 3]],
        ['first opened each door a day late', 200, (day) => `2026-12-0${day + 1}T12:00:00Z`, undefined, []],
        [
            'first opened each door on its day five hours behind UTC',
            200,
            (day) => `2026-12-0${day + 1}T02:00:00Z`,
            -300,
            [1, 2, 3],
        ],
        ['replies without the first open offset', 200, (day) => `2026-12-0${day}T12:00:00Z`, null, [1, 2, 3]],
    ])(
        'keeps only the tickets the server confirms, after a reload too, when it %s',
        async (_, reply, openedAt, storedOffset, ticketDays) => {
            useMocks(calendarApi({ open: reply, openedAt, storedOffset }).mocks)
            logic.actions.activateDoor('door-1')
            logic.actions.finishReveal()
            logic.actions.answerDoor('door-2', 'james')
            logic.actions.finishReveal()
            logic.actions.activateDoor('door-3-upper')
            await waitFor(() => expect(logic.values.ticketDays).toEqual(ticketDays))
            await expectLogic(logic).toFinishAllListeners()

            logic.unmount()
            logic = adventCalendarLogic()
            logic.mount()

            expect([logic.values.ticketDays, logic.values.tickets]).toEqual([ticketDays, ticketDays.length])
        }
    )

    const LATE = { openedAt: () => '2026-12-04T09:00:00Z' }
    const OLD_FORMAT = (): void => {
        window.localStorage.setItem(
            KEY,
            JSON.stringify({ [UUID]: { opened: [1, 2, 3], answers: { 2: 'james' }, onTime: [3] } })
        )
        window.localStorage.setItem(TICKETS_KEY, JSON.stringify({ [UUID]: 3 }))
    }

    it.each<
        [
            string,
            Parameters<typeof calendarApi>[0],
            'reload' | 'close' | 'another tab' | 'another tab waits',
            Parameters<typeof calendarApi>[0],
            number,
        ]
    >([
        ['the reply confirms the open, and the server refuses opens after the reload', {}, 'reload', { open: 403 }, 1],
        ['the reply puts the first open on another day', LATE, 'reload', {}, 0],
        ['the server refuses the open', { open: 403 }, 'reload', {}, 0],
        [
            'the reply is lost on the network, and the server confirms it after the reload',
            { open: 'network error' },
            'reload',
            {},
            1,
        ],
        ['the server fails, and puts the first open on another day after the reload', { open: 500 }, 'reload', LATE, 0],
        [
            'the page reloads before the reply, and the server confirms it after the reload',
            { openHeld: new Promise(() => {}) },
            'reload',
            {},
            1,
        ],
        [
            'the page reloads before the reply, and the server has it on another day',
            { openHeld: new Promise(() => {}) },
            'reload',
            LATE,
            0,
        ],
        ['the calendar closes before the reply comes back', {}, 'close', {}, 1],
        [
            'another tab saves its tickets without this one, and the server refuses opens after the reload',
            {},
            'another tab',
            { open: 403 },
            1,
        ],
        [
            'another tab saves an open it waits on, and the server has it on its day after the reload',
            {},
            'another tab waits',
            { openedAt: (day) => `2026-12-0${day}T09:00:00Z` },
            2,
        ],
    ])('shows the right tickets after a reload when %s', async (_, first, between, afterReload, tickets) => {
        let reply: () => void = () => {}
        const held = between === 'close' ? new Promise<void>((resolve) => (reply = resolve)) : first?.openHeld
        const firstApi = calendarApi({ ...first, openHeld: held })
        useMocks(firstApi.mocks)
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', 'james')
        logic.actions.finishReveal()
        if (between === 'another tab waits') {
            await waitFor(() => expect(firstApi.opens).toHaveLength(2))
            await jest.advanceTimersByTimeAsync(100)
            window.localStorage.setItem(PENDING_KEY, JSON.stringify({ [UUID]: [2] }))
        }
        logic.actions.activateDoor('door-3-upper')
        await waitFor(() => expect(firstApi.opens).toHaveLength(3))
        await jest.advanceTimersByTimeAsync(100)

        if (between === 'another tab') {
            window.localStorage.setItem(TICKETS_KEY, JSON.stringify({ [UUID]: [] }))
            window.dispatchEvent(new StorageEvent('storage', { key: TICKETS_KEY }))
        }
        logic.unmount()
        if (between === 'close') {
            reply()
            await jest.advanceTimersByTimeAsync(100)
        }
        useMocks(calendarApi(afterReload).mocks)
        logic = adventCalendarLogic()
        logic.mount()
        await jest.advanceTimersByTimeAsync(100)

        expect(logic.values.tickets).toBe(tickets)
    })

    it.each<[string, Reply, Reply, number[], number[]]>([
        ['the open was lost on the network, and the re-send reaches the server', 'network error', 200, [3], []],
        ['the open was lost on the network, and the re-send is lost too', 'network error', 'network error', [3], [3]],
        ['the server took the open', 200, 200, [], []],
    ])(
        'sends each waiting open once when the browser is back online after %s',
        async (_, first, resend, resent, pending) => {
            const firstApi = calendarApi({ open: first })
            useMocks(firstApi.mocks)
            logic.actions.activateDoor('door-1')
            logic.actions.finishReveal()
            logic.actions.answerDoor('door-2', 'james')
            logic.actions.finishReveal()
            logic.actions.activateDoor('door-3-upper')
            await waitFor(() => expect(firstApi.opens).toHaveLength(3))
            await jest.advanceTimersByTimeAsync(100)

            const onlineApi = calendarApi({ open: resend })
            useMocks(onlineApi.mocks)
            window.dispatchEvent(new Event('online'))
            await jest.advanceTimersByTimeAsync(60_000)

            expect({
                resent: onlineApi.opens.map((open) => (open as { day: number }).day),
                tickets: logic.values.tickets,
                pending: logic.values.pendingTicketsByUser[UUID] ?? [],
            }).toEqual({ resent, tickets: 1, pending })
        }
    )

    it('counts no ticket from a stored format no release wrote', () => {
        OLD_FORMAT()
        logic.unmount()
        logic = adventCalendarLogic()
        logic.mount()

        expect([doorOf(logic, 'door-3-upper')?.status, logic.values.tickets]).toEqual(['open', 0])
    })

    it('earns a ticket for every door a preview opens, and saves none of them', async () => {
        const api = calendarApi()
        useMocks(api.mocks)
        signIn({ is_staff: true })
        router.actions.push('/workflows/advent', { day: '4' })
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', 'james')
        logic.actions.finishReveal()
        logic.actions.activateDoor('door-3-upper')
        await expectLogic(logic).toFinishAllListeners()

        const preview = { tickets: logic.values.tickets, flight: logic.values.ticketFlight }
        router.actions.push('/workflows/advent')
        logic.unmount()
        logic = adventCalendarLogic()
        logic.mount()

        expect(preview).toEqual({ tickets: 3, flight: 3 })
        expect({
            door: doorOf(logic, 'door-1')?.status,
            tickets: logic.values.tickets,
            opens: api.opens,
            events: sent.filter(([event]) => event === 'workflows advent door opened'),
        }).toEqual({ door: 'ready', tickets: 0, opens: [], events: [] })
    })

    it('keeps a door shut until its day comes, then unlocks it on an open page', () => {
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', 'james')
        logic.actions.finishReveal()
        logic.actions.activateDoor('door-3-upper')
        logic.actions.finishReveal()
        logic.actions.activateDoor('door-4-upper')

        expect(doorOf(logic, 'door-3-upper')?.status).toBe('open')
        expect(doorOf(logic, 'door-4-upper')?.status).toBe('locked')
        expect(logic.values.openCount).toBe(3)

        jest.advanceTimersByTime(15 * 60 * 60 * 1000)

        expect(doorOf(logic, 'door-4-upper')?.status).toBe('ready')
    })

    it('keeps the progress and the pick another tab saved, shows its shares, and sends no second answer, when this tab answers again', async () => {
        const other = '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e02'
        useMocks(calendarApi({}, resultsOf({ ...DAY_TWO_ANSWERED, answer: null })).mocks)
        await expectLogic(logic, () => logic.actions.loadPollResults()).toFinishAllListeners()
        const api = calendarApi()
        useMocks(api.mocks)
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        window.localStorage.setItem(
            KEY,
            JSON.stringify({
                [UUID]: { opened: [1, 2], answers: { 2: 'tim' } },
                [other]: { opened: [1], answers: {} },
            })
        )
        window.localStorage.setItem(TICKETS_KEY, JSON.stringify({ [UUID]: [2] }))

        await expectLogic(logic, () => logic.actions.answerDoor('door-2', 'james')).toFinishAllListeners()
        const shares = logic.values.pollShares
        await waitFor(() => expect(logic.values.tickets).toBe(1))
        logic.unmount()
        logic = adventCalendarLogic()
        logic.mount()
        const mine = { door: doorOf(logic, 'door-2'), tickets: logic.values.tickets }
        signIn({ uuid: other })

        expect({ shares, mine, answers: api.answers }).toEqual({
            shares: { 2: { james: 38, tim: 62 } },
            mine: { door: { status: 'open', reward: 'Tim Glaser' }, tickets: 1 },
            answers: [],
        })
        expect([doorOf(logic, 'door-1')?.status, doorOf(logic, 'door-2')?.status, logic.values.tickets]).toEqual([
            'open',
            'ready',
            0,
        ])
    })

    it('keeps the opened doors of each account apart in one browser', () => {
        logic.actions.activateDoor('door-1')

        signIn({ uuid: '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e02' })

        expect(doorOf(logic, 'door-1')?.status).toBe('ready')
        expect(logic.values.openCount).toBe(0)
    })

    it('ignores another door while a reveal runs, then opens it once the reveal ends', () => {
        logic.actions.activateDoor('door-1')
        logic.actions.answerDoor('door-2', 'tim')

        expect(logic.values.revealingDoor?.id).toBe('door-1')
        expect(doorOf(logic, 'door-2')?.status).toBe('ready')

        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', 'tim')

        expect(logic.values.revealingDoor?.id).toBe('door-2')
        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
    })

    it.each([
        ['an answer no option has', { opened: [1, 2, 3], answers: { 2: 'tmi' } }],
        ['no answer', { opened: [1, 2, 3], answers: {} }],
    ])(
        'lets the person answer a question again when storage holds %s for it, and keeps every saved open',
        (_, progress) => {
            const other = '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e02'
            logic.unmount()
            window.localStorage.setItem(KEY, JSON.stringify({ [UUID]: progress, [other]: progress }))
            logic = adventCalendarLogic()
            logic.mount()

            expect(doorOf(logic, 'door-2')?.status).toBe('ready')
            expect(logic.values.openCount).toBe(1)

            logic.actions.answerDoor('door-2', 'tim')

            expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
            expect(JSON.parse(window.localStorage.getItem(KEY)!)).toEqual({
                [UUID]: { opened: [1, 2, 3], answers: { 2: 'tim' } },
                [other]: { opened: [1, 2, 3], answers: {} },
            })
        }
    )

    it.each(['null', `{"${UUID}":{"opened":3}}`])('keeps working when storage holds %s at load', (value) => {
        const uncaught: ErrorEvent[] = []
        const onError = (event: ErrorEvent): number => uncaught.push(event)
        window.addEventListener('error', onError)
        logic.unmount()
        window.localStorage.setItem(KEY, value)
        logic = adventCalendarLogic()
        logic.mount()
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', 'tim')
        window.removeEventListener('error', onError)

        logic.unmount()
        logic = adventCalendarLogic()
        logic.mount()

        expect(uncaught).toEqual([])
        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
        expect(doorOf(logic, 'door-3-lower')?.status).toBe('ready')
        expect(logic.values.openCount).toBe(2)
    })

    it('opens a question door with the answer and puffs away the path not taken', async () => {
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()

        await expectLogic(logic, () => {
            logic.actions.answerDoor('door-2', 'tim')
        }).toMatchValues({
            snowPuffs: [
                expect.objectContaining({ id: 'door-3-upper' }),
                expect.objectContaining({ id: 'door-4-upper' }),
            ],
        })

        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
        expect(doorOf(logic, 'door-3-upper')).toBeNull()
        expect(doorOf(logic, 'door-3-lower')?.status).toBe('ready')
        expect(capture).toHaveBeenCalledWith('workflows advent answer picked', { day: 2, option: 'tim' })
    })

    it.each<[Reply, object]>([
        [200, { 2: { james: 38, tim: 62 } }],
        [403, {}],
        [429, {}],
        [500, {}],
        ['network error', {}],
    ])(
        'sends a picked answer to the server, keeps the pick, and shows the shares when it replies %s',
        async (reply, shares) => {
            const api = calendarApi({ answer: reply, results: 403 })
            useMocks(api.mocks)
            logic.actions.activateDoor('door-1')
            logic.actions.finishReveal()

            await expectLogic(logic, () => logic.actions.answerDoor('door-2', 'tim')).toFinishAllListeners()

            expect(api.answers).toEqual([{ day: 2, option: 'tim' }])
            expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
            expect(logic.values.pollShares).toEqual(shares)
        }
    )

    it.each<[string, Reply, object, object]>([
        ['an answered question', 200, DAY_TWO_ANSWERED, { 2: { james: 38, tim: 62 } }],
        ['a question the person did not answer', 200, { ...DAY_TWO_ANSWERED, answer: null }, {}],
        ['an answer this browser did not pick', 200, { ...DAY_TWO_ANSWERED, answer: 'james' }, {}],
        ['a 403', 403, DAY_TWO_ANSWERED, {}],
        ['a 429', 429, DAY_TWO_ANSWERED, {}],
        ['a 500', 500, DAY_TWO_ANSWERED, {}],
        ['a network error', 'network error', DAY_TWO_ANSWERED, {}],
    ])('loads the shares when the calendar opens, and shows them only for %s', async (_, reply, question, shares) => {
        useMocks(calendarApi({ results: reply }, resultsOf(question)).mocks)
        logic.unmount()
        window.localStorage.setItem(KEY, JSON.stringify({ [UUID]: { opened: [1, 2], answers: { 2: 'tim' } } }))
        logic = adventCalendarLogic()

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        expect(logic.values.pollShares).toEqual(shares)
    })

    const OLDER_DAY_TWO = {
        ...DAY_TWO_ANSWERED,
        shares: [
            { option: 'james', share: 50 },
            { option: 'tim', share: 50 },
        ],
    }

    it.each<[string, object, 'answer' | 'read' | 'remount']>([
        ['an answer save, without the answer', { ...DAY_TWO_ANSWERED, answer: null }, 'answer'],
        ['an answer save, with the answer at older shares', OLDER_DAY_TWO, 'answer'],
        ['a newer results read, with the answer at older shares', OLDER_DAY_TWO, 'read'],
        ['the calendar opened again, with the answer at older shares', OLDER_DAY_TWO, 'remount'],
    ])(
        'keeps the newer shares when the results the calendar loaded first arrive after %s',
        async (_, lateQuestion, overtakenBy) => {
            let release = (): void => {}
            const api = calendarApi({}, resultsOf(lateQuestion), new Promise((done) => (release = done)))
            useMocks(api.mocks)
            if (overtakenBy === 'read') {
                window.localStorage.setItem(KEY, JSON.stringify({ [UUID]: { opened: [1, 2], answers: { 2: 'tim' } } }))
            }
            logic.unmount()
            logic = adventCalendarLogic()
            logic.mount()
            await waitFor(() => expect(api.reads).toEqual([1]))
            useMocks(calendarApi().mocks)
            if (overtakenBy === 'remount') {
                logic.unmount()
                window.localStorage.setItem(KEY, JSON.stringify({ [UUID]: { opened: [1, 2], answers: { 2: 'tim' } } }))
                logic = adventCalendarLogic()
                logic.mount()
            } else if (overtakenBy === 'read') {
                logic.actions.loadPollResults()
            } else {
                logic.actions.activateDoor('door-1')
                logic.actions.finishReveal()
                logic.actions.answerDoor('door-2', 'tim')
            }
            await waitFor(() => expect(logic.values.pollShares).toEqual({ 2: { james: 38, tim: 62 } }))
            release()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.pollShares).toEqual({ 2: { james: 38, tim: 62 } })
        }
    )

    it('drops the results a read started before the calendar was opened again, when the new read fails', async () => {
        let release = (): void => {}
        const api = calendarApi({}, resultsOf(OLDER_DAY_TWO), new Promise((done) => (release = done)))
        useMocks(api.mocks)
        logic.unmount()
        logic.mount()
        await waitFor(() => expect(api.reads).toEqual([1]))
        const failing = calendarApi({ results: 500 })
        useMocks(failing.mocks)
        logic.unmount()
        logic.mount()
        await waitFor(() => expect(failing.reads).toEqual([1]))
        signIn({ uuid: UUID, is_staff: false })
        logic.actions.openDoor(UUID, 1, null, true, false)
        logic.actions.openDoor(UUID, 2, 'tim', true, false)
        release()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.pollShares).toEqual({})
    })

    it.each(['before', 'after'])(
        'shows the shares of both answers when the server reply to the first is held %s it saves the answer',
        async (held) => {
            let release = (): void => {}
            const hold = new Promise<void>((done) => (release = done))
            const dayFive = {
                day: 5,
                answer: 'yes',
                shares: [
                    { option: 'no', share: 30 },
                    { option: 'yes', share: 70 },
                ],
            }
            const saved: number[] = []
            const snapshot = (): object =>
                resultsOf(
                    saved.includes(2) ? DAY_TWO_ANSWERED : { ...DAY_TWO_ANSWERED, answer: null },
                    saved.includes(5) ? dayFive : { ...dayFive, answer: null }
                )
            useMocks({
                get: { [`${CALENDAR_API}/results/`]: () => [200, snapshot()] },
                post: {
                    [`${CALENDAR_API}/answer/`]: async ({ request }) => {
                        const { day } = (await request.json()) as { day: number }
                        if (day === 2 && held === 'before') {
                            await hold
                        }
                        saved.push(day)
                        const reply = snapshot()
                        if (day === 2 && held === 'after') {
                            await hold
                        }
                        return [200, reply]
                    },
                    [`${CALENDAR_API}/open/`]: () => [200, {}],
                },
            })
            jest.setSystemTime(new Date(2026, 11, 5, 9, 0))
            logic.actions.refreshClock()
            logic.actions.activateDoor('door-1')
            logic.actions.finishReveal()
            logic.actions.answerDoor('door-2', 'tim')
            logic.actions.finishReveal()
            for (const door of ['door-3-lower', 'door-4-lower']) {
                logic.actions.activateDoor(door)
                logic.actions.finishReveal()
            }

            logic.actions.answerDoor('door-5', 'yes')
            await waitFor(() => expect(logic.values.pollShares[5]).toEqual({ no: 30, yes: 70 }))
            release()
            await expectLogic(logic).toFinishAllListeners()

            expect([...saved].sort()).toEqual([2, 5])
            expect(logic.values.pollShares).toEqual({ 2: { james: 38, tim: 62 }, 5: { no: 30, yes: 70 } })
        }
    )

    type PollRequest = 'read' | 'save 2' | 'save 5'

    const permutations = <T>(items: T[]): T[][] =>
        items.length <= 1
            ? [items]
            : items.flatMap((item, index) =>
                  permutations([...items.slice(0, index), ...items.slice(index + 1)]).map((rest) => [item, ...rest])
              )

    const POLL_REQUEST_SETS: PollRequest[][] = [
        ['read', 'save 2'],
        ['read', 'save 5'],
        ['save 2', 'save 5'],
        ['read', 'save 2', 'save 5'],
    ]

    const POLL_INTERLEAVINGS = POLL_REQUEST_SETS.flatMap((requests) =>
        permutations(requests).flatMap((started) =>
            permutations(requests).flatMap((served) =>
                permutations(requests).map((replied): [string, PollRequest[], PollRequest[], PollRequest[]] => [
                    `started ${started.join(', ')}; served ${served.join(', ')}; replied ${replied.join(', ')}`,
                    started,
                    served,
                    replied,
                ])
            )
        )
    )

    it.each(POLL_INTERLEAVINGS)(
        "shows the server's latest shares once every request settled: %s",
        async (_, started, served, replied) => {
            const PICKS = { 2: 'tim', 5: 'yes' } as const
            const dayOf = (request: PollRequest): 2 | 5 => (request === 'save 2' ? 2 : 5)
            const answered = new Set<number>()
            let version = 0
            const snapshot = (): { questions: object[] } =>
                resultsOf(
                    ...[2, 5].map((day) => ({
                        day,
                        answer: answered.has(day) ? PICKS[day as 2 | 5] : null,
                        shares:
                            day === 2
                                ? [
                                      { option: 'james', share: 40 - version },
                                      { option: 'tim', share: 60 + version },
                                  ]
                                : [
                                      { option: 'no', share: 30 - version },
                                      { option: 'yes', share: 70 + version },
                                  ],
                    }))
                )
            const serve = (request: PollRequest): object => {
                version += 1
                if (request !== 'read') {
                    answered.add(dayOf(request))
                }
                return snapshot()
            }
            const gate = (): { open: () => void; opened: Promise<void> } => {
                let open = (): void => {}
                const opened = new Promise<void>((done) => (open = done))
                return { open, opened }
            }
            const held = new Map<PollRequest, { serve: ReturnType<typeof gate>; reply: ReturnType<typeof gate> }>()
            const bodies = new Map<PollRequest, object>()
            const arrived = new Set<PollRequest>()
            let sent = 0
            const handle = async (request: PollRequest): Promise<[number, object]> => {
                sent += 1
                const gates = held.get(request)
                if (!gates || arrived.has(request)) {
                    return [200, serve(request)]
                }
                arrived.add(request)
                await gates.serve.opened
                bodies.set(request, serve(request))
                await gates.reply.opened
                return [200, bodies.get(request)!]
            }
            window.localStorage.setItem(KEY, JSON.stringify({ [UUID]: { opened: [1, 2, 3, 4, 5], answers: PICKS } }))
            useMocks({
                get: { [`${CALENDAR_API}/results/`]: () => handle('read') },
                post: {
                    [`${CALENDAR_API}/answer/`]: async ({ request }) =>
                        handle(`save ${((await request.json()) as { day: number }).day}` as PollRequest),
                },
            })
            logic.unmount()
            logic = adventCalendarLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            sent = 0
            for (const request of started) {
                held.set(request, { serve: gate(), reply: gate() })
            }

            for (const request of started) {
                if (request === 'read') {
                    logic.actions.loadPollResults()
                } else {
                    logic.actions.savePollAnswer({ day: dayOf(request), option: PICKS[dayOf(request)] })
                }
            }
            await waitFor(() => expect(sent).toBe(started.length))
            for (const request of served) {
                held.get(request)!.serve.open()
                await waitFor(() => expect(bodies.has(request)).toBe(true))
            }
            for (const request of replied) {
                held.get(request)!.reply.open()
                const body = JSON.stringify(bodies.get(request))
                await expectLogic(logic).toDispatchActions([
                    (action) =>
                        action.type === logic.actionTypes.receivePollResults &&
                        JSON.stringify(action.payload.results) === body,
                ])
            }
            await expectLogic(logic).toFinishAllListeners()

            const latest = snapshot().questions as {
                day: number
                answer: string | null
                shares: { option: string; share: number }[]
            }[]
            expect(logic.values.pollShares).toEqual(
                Object.fromEntries(
                    latest
                        .filter((question) => question.answer)
                        .map((question) => [
                            question.day,
                            Object.fromEntries(question.shares.map((share) => [share.option, share.share])),
                        ])
                )
            )
            expect(sent).toBeLessThanOrEqual(started.length + 1)
        }
    )

    it('sends no door opens or answers while a staff user previews another day, and keeps the live doors shut', async () => {
        const api = calendarApi()
        useMocks(api.mocks)
        preflightLogic.actions.loadPreflightSuccess({ ...preflightLogic.values.preflight!, is_debug: false })
        signIn({ is_staff: true })
        router.actions.push('/workflows/advent', { day: '2' })
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', 'tim')
        logic.actions.loadPollResults()

        await waitFor(() => expect(api.reads).toHaveLength(1))
        await expectLogic(logic).toFinishAllListeners()

        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
        expect({ opens: api.opens, answers: api.answers }).toEqual({ opens: [], answers: [] })

        router.actions.push('/workflows/advent')
        expect(doorOf(logic, 'door-1')?.status).toBe('ready')
        logic.actions.activateDoor('door-1')

        await waitFor(() => expect(api.opens).toMatchObject([{ day: 1 }]))
    })

    it('shows the pick another tab saved when a staff preview answers the same door', async () => {
        useMocks(calendarApi().mocks)
        signIn({ is_staff: true })
        router.actions.push('/workflows/advent', { day: '2' })
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        window.localStorage.setItem(KEY, JSON.stringify({ [UUID]: { opened: [1, 2], answers: { 2: 'tim' } } }))
        logic.actions.answerDoor('door-2', 'james')
        await expectLogic(logic).toFinishAllListeners()

        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
    })

    it("drops preview progress once a live open takes in another tab's pick", async () => {
        useMocks(calendarApi().mocks)
        signIn({ is_staff: true })
        router.actions.push('/workflows/advent', { day: '4' })
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', 'james')
        logic.actions.finishReveal()
        logic.actions.activateDoor('door-3-upper')
        logic.actions.finishReveal()
        window.localStorage.setItem(KEY, JSON.stringify({ [UUID]: { opened: [1, 2], answers: { 2: 'tim' } } }))
        router.actions.push('/workflows/advent')
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        router.actions.push('/workflows/advent', { day: '4' })
        await expectLogic(logic).toFinishAllListeners()

        expect(doorOf(logic, 'door-3-lower')?.status).toBe('ready')
    })

    it.each([
        ['a staff user', 'locked', true],
        ['anyone else', 'ready', false],
    ])('shows %s door 2 as %s with ?day=1 on 3 December', (_, doorTwo, isStaff) => {
        preflightLogic.actions.loadPreflightSuccess({ ...preflightLogic.values.preflight!, is_debug: false })
        signIn({ is_staff: isStaff })
        router.actions.push('/workflows/advent', { day: '1' })
        logic.actions.activateDoor('door-1')

        expect(doorOf(logic, 'door-2')?.status).toBe(doorTwo)
    })

    it.each([
        ['anyone', 'on 27 November', 24, new Date(2026, 10, 27, 9, 0), false],
        ['anyone else', 'on 1 December', 1, new Date(2026, 11, 1, 9, 0), false],
        ['a staff user', 'on 1 December', 24, new Date(2026, 11, 1, 9, 0), true],
    ])('shows %s %s with ?day=24 the day %s', (_, __, today, now, isStaff) => {
        jest.setSystemTime(now)
        logic.actions.refreshClock()
        preflightLogic.actions.loadPreflightSuccess({ ...preflightLogic.values.preflight!, is_debug: false })
        signIn({ is_staff: isStaff })
        router.actions.push('/workflows/advent', { day: '24' })

        expect(logic.values.today).toBe(today)
    })

    it.each([
        ['a staff user previews the real day', true, new Date(2026, 11, 2, 9, 0), { day: '2' }, [], 0, false],
        ['anyone previews a day in November', false, new Date(2026, 10, 27, 9, 0), { day: '2' }, [], 0, false],
        ['a staff user opens the real day', true, new Date(2026, 11, 2, 9, 0), {}, [1, 2], 1, true],
    ])(
        'when %s, it sends and stores only what is live',
        async (_, isStaff, now, searchParams, opens, answers, isLive) => {
            const api = calendarApi()
            useMocks(api.mocks)
            jest.setSystemTime(now)
            logic.actions.refreshClock()
            preflightLogic.actions.loadPreflightSuccess({ ...preflightLogic.values.preflight!, is_debug: false })
            signIn({ is_staff: isStaff })
            router.actions.push('/workflows/advent', searchParams)
            const storedBefore = window.localStorage.getItem('workflows-advent-calendar-progress')
            logic.actions.activateDoor('door-1')
            logic.actions.finishReveal()
            logic.actions.answerDoor('door-2', ADVENT_QUESTIONS[2].options[0].id)

            await waitFor(() => expect(api.opens).toHaveLength(opens.length))
            await waitFor(() => expect(api.answers).toHaveLength(answers))
            await expectLogic(logic).toFinishAllListeners()

            expect(doorOf(logic, 'door-2')?.status).toBe('open')
            expect({
                opens: api.opens.map((open) => (open as { day: number }).day),
                answers: api.answers.length,
                storesProgress: window.localStorage.getItem('workflows-advent-calendar-progress') !== storedBefore,
                openEvents: sent.filter(([event]) => event === 'workflows advent door opened').length,
                answerEvents: sent.filter(([event]) => event === 'workflows advent answer picked').length,
            }).toEqual({ opens, answers, storesProgress: isLive, openEvents: opens.length, answerEvents: answers })
        }
    )

    it('lets anyone who previewed doors in November open and answer them for real on 2 December', async () => {
        const api = calendarApi()
        useMocks(api.mocks)
        jest.setSystemTime(new Date(2026, 10, 27, 9, 0))
        logic.actions.refreshClock()
        router.actions.push('/workflows/advent', { day: '2' })
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', ADVENT_QUESTIONS[2].options[0].id)
        await expectLogic(logic).toFinishAllListeners()

        logic.unmount()
        jest.setSystemTime(new Date(2026, 11, 2, 9, 0))
        router.actions.push('/workflows/advent')
        logic = adventCalendarLogic()
        logic.mount()
        logic.actions.refreshClock()
        const doorsBefore = [doorOf(logic, 'door-1')?.status, doorOf(logic, 'door-2')?.status]
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()
        logic.actions.answerDoor('door-2', ADVENT_QUESTIONS[2].options[0].id)
        await waitFor(() => expect(api.answers).toHaveLength(1))

        expect({ doorsBefore, opens: api.opens.map((open) => (open as { day: number }).day) }).toEqual({
            doorsBefore: ['ready', 'locked'],
            opens: [1, 2],
        })
    })

    it.each<[string, boolean, unknown[][]]>([
        [
            'live',
            false,
            [
                ['workflows advent tip clicked', { day: 7 }],
                ['workflows advent shared', {}],
            ],
        ],
        ['in a staff preview of another day', true, []],
    ])('reports a tip click with its day and a share %s', (_, isPreview, sent) => {
        if (isPreview) {
            preflightLogic.actions.loadPreflightSuccess({ ...preflightLogic.values.preflight!, is_debug: false })
            signIn({ is_staff: true })
            router.actions.push('/workflows/advent', { day: '2' })
        }
        capture.mockClear()
        logic.actions.clickTip(7)
        logic.actions.share()

        expect(capture.mock.calls).toEqual(sent)
    })
})
