import { act, fireEvent, render, RenderResult } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { Mocks } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { adventCalendarLogic } from './adventCalendarLogic'
import { ADVENT_QUESTION_DAYS, ADVENT_QUESTIONS } from './adventContent'
import { AdventRaffleFlowStage } from './AdventRaffleFlowStage'
import { ADVENT_FLOW_OPENING_MS } from './flow/AdventFlowStage'

const UUID = '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01'
const DAYS = Array.from({ length: 24 }, (_, index) => index + 1)
const DESKTOP = { width: 1200, height: 830 }
const PHONE = { width: 375, height: 700 }
const ANSWERS = Object.fromEntries(ADVENT_QUESTION_DAYS.map((day) => [day, ADVENT_QUESTIONS[day].options[0].id]))

function calendarMocks(tickets: number[]): Mocks {
    return {
        get: {
            '/api/projects/:team_id/workflow_advent_calendar/results/': { questions: [], ticket_days: tickets },
        },
        post: {
            '/api/projects/:team_id/workflow_advent_calendar/open/': async ({ request }) => {
                const { day } = (await request.json()) as { day: number }
                return [200, { day, opened_at: new Date().toISOString(), ticket_days: [...tickets, day] }]
            },
        },
    }
}

describe('AdventRaffleFlowStage', () => {
    let capture: jest.SpyInstance
    let measure: jest.SpyInstance
    let stage: RenderResult | null

    async function renderOn(now: Date, opened: number[], size: { width: number; height: number }): Promise<void> {
        jest.useFakeTimers({ now, advanceTimers: true })
        window.localStorage.setItem(
            'workflows-advent-calendar-progress',
            JSON.stringify({ [UUID]: { opened, answers: ANSWERS } })
        )
        initKeaTests()
        await expectLogic(userLogic).toFinishAllListeners()
        userLogic.actions.loadUserSuccess({ ...userLogic.values.user, uuid: UUID } as UserType)
        measure.mockReturnValue(size as DOMRect)
        adventCalendarLogic.mount()
        await expectLogic(adventCalendarLogic).toFinishAllListeners()
        stage = render(<AdventRaffleFlowStage />)
    }

    const door = (day: number): HTMLElement =>
        document.querySelector(`[data-attr="advent-door-${day}"], [data-attr="advent-hog-${day}"]`) as HTMLElement
    const card = (): HTMLElement | null => document.querySelector('[data-attr="advent-door-card"]')
    const flight = (): HTMLElement | null => document.querySelector('[data-attr="advent-ticket-flight"]')
    const advance = async (...steps: number[]): Promise<void> => {
        for (const step of steps) {
            await act(async () => {
                await jest.advanceTimersByTimeAsync(step)
            })
        }
    }

    beforeEach(() => {
        window.localStorage.clear()
        jest.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
        measure = jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
        stage = null
    })

    afterEach(() => {
        stage?.unmount()
        adventCalendarLogic.findMounted()?.unmount()
        measure.mockRestore()
        capture.mockRestore()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('draws the gold trail only into doors opened on their day', async () => {
        useMocks(calendarMocks([1, 3, 4]))
        await renderOn(new Date(2026, 11, 6, 9, 0), [1, 2, 3, 4, 5], DESKTOP)

        expect(
            Array.from(document.querySelectorAll('[data-emphasized="true"]')).map(
                (edge) => edge.getAttribute('data-edge')?.split('>')[1].split('-')[1]
            )
        ).toEqual(['1', '3', '4'])
    })

    it('opens the card on the present once its opening has played', async () => {
        useMocks(calendarMocks([]))
        await renderOn(new Date(2026, 11, 24, 9, 0), DAYS.slice(0, 23), DESKTOP)

        act(() => fireEvent.click(door(24)))
        await advance(ADVENT_FLOW_OPENING_MS - 100)
        const beforeTheEnd = card()?.getAttribute('data-open') ?? null
        await advance(200, 100)

        expect([beforeTheEnd, card()?.getAttribute('data-open')]).toEqual([null, 'true'])
    })

    it('holds the ticket flight while the door card covers the phone column', async () => {
        useMocks(calendarMocks([1]))
        await renderOn(new Date(2026, 11, 3, 9, 0), [1, 2], PHONE)

        act(() => fireEvent.click(door(3)))
        await advance(ADVENT_FLOW_OPENING_MS, 200, 100)
        const whileTheCardIsOpen = [card()?.getAttribute('data-open'), !!flight()]
        act(() => fireEvent.click(card()?.querySelector('[data-attr="advent-door-card-close"]') as HTMLElement))
        await advance(300, 300, 100)

        expect([whileTheCardIsOpen, !!flight()]).toEqual([['true', false], true])
    })
})
