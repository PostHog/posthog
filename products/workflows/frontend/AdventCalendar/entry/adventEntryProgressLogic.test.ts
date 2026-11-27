import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { ADVENT_YEAR } from '../adventContent'
import { PROGRESS_STORAGE_KEY } from '../adventProgressStorage'
import { adventEntryProgressLogic } from './adventEntryProgressLogic'

function storeProgress(stored: unknown): void {
    window.localStorage.setItem(PROGRESS_STORAGE_KEY, typeof stored === 'string' ? stored : JSON.stringify(stored))
}

function mountAt(now: Date): typeof adventEntryProgressLogic {
    jest.setSystemTime(now)
    adventEntryProgressLogic.mount()
    return adventEntryProgressLogic
}

function openedDoorDays(logic: typeof adventEntryProgressLogic): number[] | null {
    return logic.values.doors?.filter((door) => door.status === 'open').map((door) => door.day) ?? null
}

function decemberMorning(day: number): Date {
    return day > 0 ? new Date(ADVENT_YEAR, 11, day, 9) : new Date(ADVENT_YEAR, 10, 27, 9)
}

describe('adventEntryProgressLogic', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        window.localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        adventEntryProgressLogic.unmount()
        jest.useRealTimers()
    })

    it.each([
        ['is unknown while no user is loaded', null, { [MOCK_DEFAULT_USER.uuid]: { opened: [1] } }, null],
        ['reads the doors this person opened', MOCK_DEFAULT_USER, { [MOCK_DEFAULT_USER.uuid]: { opened: [1] } }, [1]],
        ['is empty when only someone else opened doors', MOCK_DEFAULT_USER, { other: { opened: [1] } }, []],
        [
            'stops before a question door left unanswered',
            MOCK_DEFAULT_USER,
            { [MOCK_DEFAULT_USER.uuid]: { opened: [1, 2, 3] } },
            [1],
        ],
        ['is empty when the stored progress is unreadable', MOCK_DEFAULT_USER, 'not json', []],
    ])('%s', (_, user, stored, opened) => {
        userLogic.actions.loadUserSuccess(user)
        storeProgress(stored)

        const logic = mountAt(decemberMorning(3))

        expect(openedDoorDays(logic)).toEqual(opened)
    })

    it.each([
        ['the first door with nothing opened on December 3', 3, [], {}, 1],
        ["today's door once the doors before it are open", 3, [1, 2], { 2: 'james' }, 3],
        ["no door once today's door is open", 3, [1, 2, 3], { 2: 'james' }, null],
        ['no door before December', 0, [], {}, null],
    ])('points the button at %s', (_, day, opened, answers, nextDoorDay) => {
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        storeProgress({ [MOCK_DEFAULT_USER.uuid]: { opened, answers } })

        const logic = mountAt(decemberMorning(day))

        expect(logic.values.nextDoorDay).toBe(nextDoorDay)
    })

    it('opens the first door at midnight on December 1 without a remount', () => {
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        const logic = mountAt(new Date(ADVENT_YEAR, 10, 30, 23, 59, 30))
        expect(logic.values.phase).toEqual({ status: 'soon' })

        jest.advanceTimersByTime(60_000)

        expect(logic.values.phase).toEqual({ status: 'open', day: 1 })
        expect(logic.values.nextDoorDay).toBe(1)
    })

    it('shows a door opened in another tab', () => {
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        const logic = mountAt(decemberMorning(3))
        expect(logic.values.nextDoorDay).toBe(1)

        storeProgress({ [MOCK_DEFAULT_USER.uuid]: { opened: [1] } })
        window.dispatchEvent(new StorageEvent('storage', { key: PROGRESS_STORAGE_KEY }))

        expect(openedDoorDays(logic)).toEqual([1])
        expect(logic.values.nextDoorDay).toBe(2)
    })
})
