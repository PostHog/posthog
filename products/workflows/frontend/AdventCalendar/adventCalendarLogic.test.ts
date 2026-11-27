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

import { adventCalendarLogic } from './adventCalendarLogic'

const KEY = 'workflows-advent-calendar-progress'
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
    replies: { answer?: Reply; results?: Reply; open?: Reply } = {},
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
                const open = (await request.json()) as { day: number }
                opens.push(open)
                return replyWith(replies.open ?? 200, { day: open.day, opened_at: '2026-12-03T09:00:00Z' })
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

    beforeEach(async () => {
        jest.useFakeTimers({ now: new Date(2026, 11, 3, 9, 0), advanceTimers: true })
        window.localStorage.clear()
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
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

    it('reports the view once the calendar mounts', () => {
        expect(capture).toHaveBeenCalledWith('workflows advent calendar viewed')
    })

    it('opens the door of the day and keeps it open after a reload', () => {
        logic.actions.activateDoor('door-1')

        expect(doorOf(logic, 'door-1')?.status).toBe('open')
        expect(capture).toHaveBeenCalledWith('workflows advent door opened', { day: 1 })

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

        await expectLogic(logic, () => logic.actions.answerDoor('door-2', 'james')).toFinishAllListeners()

        expect(JSON.parse(window.localStorage.getItem(KEY)!)).toEqual({
            [UUID]: { opened: [1, 2], answers: { 2: 'tim' } },
            [other]: { opened: [1], answers: {} },
        })
        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
        expect(logic.values.pollShares).toEqual({ 2: { james: 38, tim: 62 } })
        expect(api.answers).toEqual([])
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

    it('keeps the shares of a saved answer when the results the calendar loaded first arrive later', async () => {
        let release = (): void => {}
        const api = calendarApi(
            {},
            resultsOf({ ...DAY_TWO_ANSWERED, answer: null }),
            new Promise((done) => (release = done))
        )
        useMocks(api.mocks)
        logic.unmount()
        logic = adventCalendarLogic()
        logic.mount()
        await waitFor(() => expect(api.reads).toEqual([1]))
        useMocks(calendarApi().mocks)
        logic.actions.activateDoor('door-1')
        logic.actions.finishReveal()

        logic.actions.answerDoor('door-2', 'tim')
        await waitFor(() => expect(logic.values.pollShares).toEqual({ 2: { james: 38, tim: 62 } }))
        release()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.pollShares).toEqual({ 2: { james: 38, tim: 62 } })
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

    it('reports a tip click with its day', () => {
        logic.actions.clickTip(7)

        expect(capture).toHaveBeenCalledWith('workflows advent tip clicked', { day: 7 })
    })
})
