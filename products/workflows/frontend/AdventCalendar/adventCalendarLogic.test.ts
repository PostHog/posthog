import { router } from 'kea-router'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { adventCalendarLogic } from './adventCalendarLogic'

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

    beforeEach(() => {
        jest.useFakeTimers({ now: new Date(2026, 11, 3, 9, 0) })
        window.localStorage.clear()
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
        initKeaTests()
        signIn({ uuid: '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01', is_staff: false })
        logic = adventCalendarLogic()
        logic.mount()
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

    it('keeps a door shut until its day comes, then unlocks it on an open page', () => {
        logic.actions.activateDoor('door-1')
        logic.actions.answerDoor('door-2', 'james')
        logic.actions.activateDoor('door-3-upper')
        logic.actions.activateDoor('door-4-upper')

        expect(doorOf(logic, 'door-3-upper')?.status).toBe('open')
        expect(doorOf(logic, 'door-4-upper')?.status).toBe('locked')
        expect(logic.values.openCount).toBe(3)

        jest.advanceTimersByTime(15 * 60 * 60 * 1000)

        expect(doorOf(logic, 'door-4-upper')?.status).toBe('ready')
    })

    it('keeps the opened doors of each account apart in one browser', () => {
        logic.actions.activateDoor('door-1')

        signIn({ uuid: '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e02' })

        expect(doorOf(logic, 'door-1')?.status).toBe('ready')
        expect(logic.values.openCount).toBe(0)
    })

    it('keeps an answer saved in another tab when this tab opens the next door', () => {
        logic.actions.activateDoor('door-1')
        window.dispatchEvent(
            new StorageEvent('storage', {
                key: 'workflows-advent-calendar-progress',
                newValue: JSON.stringify({
                    '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01': { opened: [1, 2], answers: { 2: 'tim' } },
                }),
            })
        )

        logic.actions.activateDoor('door-3-lower')

        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
        expect(doorOf(logic, 'door-3-lower')?.status).toBe('open')
    })

    it.each([
        ['james', 'tim'],
        ['tim', 'james'],
    ])('settles on one answer when this tab picks %s and another picks %s', (here, there) => {
        logic.actions.activateDoor('door-1')
        logic.actions.answerDoor('door-2', here)
        window.dispatchEvent(
            new StorageEvent('storage', {
                key: 'workflows-advent-calendar-progress',
                newValue: JSON.stringify({
                    '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01': { opened: [1, 2], answers: { 2: there } },
                }),
            })
        )

        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'James Hawkins' })

        logic.unmount()
        logic = adventCalendarLogic()
        logic.mount()

        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'James Hawkins' })
    })

    it('takes the answer another tab stored before its event arrives, so the reward does not swap later', () => {
        logic.actions.activateDoor('door-1')
        window.localStorage.setItem(
            'workflows-advent-calendar-progress',
            JSON.stringify({ '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01': { opened: [1, 2], answers: { 2: 'tim' } } })
        )

        logic.actions.answerDoor('door-2', 'james')

        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
        expect(capture).not.toHaveBeenCalledWith('workflows advent answer picked', expect.anything())
    })

    it.each(['[object Object]', 'undefined', '{"0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01":{"opened":3}}'])(
        'keeps its progress when another tab stores %s',
        (newValue) => {
            const uncaught: ErrorEvent[] = []
            const onError = (event: ErrorEvent): number => uncaught.push(event)
            window.addEventListener('error', onError)
            logic.actions.activateDoor('door-1')

            window.dispatchEvent(new StorageEvent('storage', { key: 'workflows-advent-calendar-progress', newValue }))
            window.removeEventListener('error', onError)

            expect(uncaught).toEqual([])
            expect(doorOf(logic, 'door-1')?.status).toBe('open')
        }
    )

    it('opens a question door with the answer and drops the path not taken', () => {
        logic.actions.activateDoor('door-1')
        logic.actions.answerDoor('door-2', 'tim')

        expect(doorOf(logic, 'door-2')).toEqual({ status: 'open', reward: 'Tim Glaser' })
        expect(doorOf(logic, 'door-3-upper')).toBeNull()
        expect(doorOf(logic, 'door-3-lower')?.status).toBe('ready')
        expect(capture).toHaveBeenCalledWith('workflows advent answer picked', { day: 2, option: 'tim' })
    })

    it.each([
        ['a staff user', 'locked', true],
        ['anyone else', 'ready', false],
    ])('shows %s door 2 as %s with ?day=1 on 3 December', (_, doorTwo, isStaff) => {
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
