import { act, fireEvent, render, RenderResult } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { adventCalendarLogic } from '../adventCalendarLogic'
import { ADVENT_LAST_DAY, ADVENT_QUESTION_DAYS, ADVENT_QUESTIONS } from '../adventContent'
import { AdventFlowStage, AdventFlowStageProps } from './AdventFlowStage'
import { AdventFlowStepProps } from './AdventFlowStep'

const UUID = '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01'

function seed(opened: number[], answers: Record<number, string>): void {
    window.localStorage.setItem('workflows-advent-calendar-progress', JSON.stringify({ [UUID]: { opened, answers } }))
}

describe('AdventFlowStage', () => {
    let capture: jest.SpyInstance
    let measure: jest.SpyInstance
    let stage: RenderResult | null

    function renderStage(size: { width: number; height: number }, props: AdventFlowStageProps = {}): RenderResult {
        measure.mockReturnValue(size as DOMRect)
        adventCalendarLogic.mount()
        stage = render(<AdventFlowStage {...props} />)
        return stage
    }

    const door = (day: number): HTMLElement | null =>
        document.querySelector(`[data-attr="advent-door-${day}"], [data-attr="advent-hog-${day}"]`)

    const captionOf = (day: number): (string | null)[] => {
        const id = door(day)?.getAttribute('aria-describedby')
        const caption = id ? document.getElementById(id) : null
        return Array.from(caption?.children ?? []).map((line) => line.textContent)
    }

    const card = (): HTMLElement | null => document.querySelector('[data-attr="advent-door-card"]')

    const waitForTheCardToClose = (): void => {
        act(() => jest.advanceTimersByTime(300))
        act(() => jest.advanceTimersByTime(300))
    }

    beforeEach(async () => {
        jest.useFakeTimers({ now: new Date(2026, 11, 3, 9, 0), advanceTimers: true })
        window.localStorage.clear()
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
        measure = jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
        initKeaTests()
        await expectLogic(userLogic).toFinishAllListeners()
        userLogic.actions.loadUserSuccess({ ...userLogic.values.user, uuid: UUID } as UserType)
        stage = null
    })

    afterEach(() => {
        stage?.unmount()
        adventCalendarLogic.findMounted()?.unmount()
        measure.mockRestore()
        capture.mockRestore()
        jest.useRealTimers()
    })

    it.each([
        [2, 'advent-hog-2', 'Door 2, open: Tim Glaser', ['Tim Glaser', 'Tim'], '2', 1],
        [3, 'advent-door-3', 'Door 3, ready', ['Today'], '3Thu', 0],
        [4, 'advent-door-4', 'Door 4, opens December 4', [], '4Fri', 0],
        [21, 'advent-door-21', 'Door 21, opens December 21', ['Coffee or tea?'], '212 paths', 0],
    ])(
        'shows door %s as %s named "%s" with the caption lines %j, the text %j, %s hoggies and no lock icon',
        (day, dataAttr, name, caption, text, hoggies) => {
            seed([1, 2], { 2: 'tim' })
            renderStage({ width: 1200, height: 830 })

            expect([
                door(day)?.tagName,
                door(day)?.getAttribute('data-attr'),
                door(day)?.getAttribute('aria-label'),
            ]).toEqual(['BUTTON', dataAttr, name])
            expect(captionOf(day)).toEqual(caption)
            expect([door(day)?.textContent, door(day)?.querySelectorAll('img').length]).toEqual([text, hoggies])
            expect(door(day)?.querySelectorAll('svg')).toHaveLength(0)
        }
    )

    it('slides the card out over a closed door on hover, not over an open one, and pins it on a click until Escape', () => {
        seed([1, 2], { 2: 'tim' })
        renderStage({ width: 1200, height: 830 })

        act(() => fireEvent.mouseEnter(door(4) as HTMLElement))
        const face = card()?.querySelector<HTMLElement>('.AdventCard__door')
        expect([card()?.textContent, face?.querySelector('svg')]).toEqual([
            expect.stringContaining('Opens December 4.'),
            null,
        ])
        act(() => fireEvent.mouseLeave(door(4) as HTMLElement))
        waitForTheCardToClose()
        act(() => fireEvent.mouseEnter(door(2) as HTMLElement))
        expect(card()).toBeNull()

        act(() => fireEvent.click(door(2) as HTMLElement))
        expect(card()?.querySelector('[data-attr="advent-door-card-close"]')).not.toBeNull()
        act(() => fireEvent.keyDown(window, { key: 'Escape' }))
        waitForTheCardToClose()
        expect(card()).toBeNull()
    })

    it('opens the ready door on a click, plays its opening, then pins its card on the hoggy behind it', async () => {
        jest.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
        seed([1, 2], { 2: 'tim' })
        renderStage({ width: 1200, height: 830 })

        act(() => fireEvent.click(door(3) as HTMLElement))
        await act(async () => {
            await jest.advanceTimersByTimeAsync(2300)
        })
        const whileOpening = [door(3)?.getAttribute('data-attr'), card()]
        for (const step of [200, 100]) {
            await act(async () => {
                await jest.advanceTimersByTimeAsync(step)
            })
        }

        expect(whileOpening).toEqual(['advent-hog-3', null])
        expect(card()?.getAttribute('data-open')).toBe('true')
        act(() => fireEvent.click(card()?.querySelector('[data-attr="advent-door-card-close"]') as HTMLElement))
        waitForTheCardToClose()
        expect(card()).toBeNull()
    })

    it.each([
        ['Close', 2, '[data-attr="advent-door-card-close"]'],
        ['the tip link', 1, '[data-attr="advent-tip-link"]'],
    ])('moves focus into a pinned card and back to its door when Escape closes it from %s', (_, day, focused) => {
        seed([1, 2], { 2: 'tim' })
        renderStage({ width: 375, height: 700 })

        act(() => (door(day) as HTMLElement).focus())
        act(() => fireEvent.click(door(day) as HTMLElement))
        const focusInCard = document.activeElement?.getAttribute('data-attr')
        act(() => (document.querySelector(focused) as HTMLElement).focus())
        act(() => fireEvent.keyDown(window, { key: 'Escape' }))
        waitForTheCardToClose()

        expect([focusInCard, document.activeElement === door(day)]).toEqual(['advent-door-card-close', true])
    })

    it('closes a pinned card when the phone column scrolls under it', () => {
        seed([1, 2], { 2: 'tim' })
        renderStage({ width: 375, height: 700 })

        act(() => fireEvent.click(door(2) as HTMLElement))
        const isPinned = !!card()
        act(() => fireEvent.scroll(document.querySelector('.AdventFlowStage__track') as HTMLElement))
        waitForTheCardToClose()

        expect([isPinned, card()]).toEqual([true, null])
    })

    it.each([
        ['Tab from Close', 2, '[data-attr="advent-door-card-close"]', false, 3],
        ['Shift+Tab from its face', 2, '.AdventCard__face', true, 2],
        ["Tab from the last door's link", 24, '[data-attr="advent-tip-link"]', false, 24],
    ])('leaves a pinned card on %s and closes the card', (_, pinned, from, shiftKey, landsOn) => {
        seed([1, 2, 24], { 2: 'tim' })
        renderStage({ width: 1200, height: 830 })

        act(() => fireEvent.click(door(pinned) as HTMLElement))
        act(() => card()?.querySelector<HTMLElement>(from)?.focus())
        act(() => void fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Tab', shiftKey }))
        waitForTheCardToClose()

        expect([document.activeElement === door(landsOn), card()]).toEqual([true, null])
    })

    it('keeps focus in a pinned card after a keyboard answer opens its door', async () => {
        jest.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
        seed([1], {})
        renderStage({ width: 1200, height: 830 })

        act(() => fireEvent.click(door(2) as HTMLElement))
        const option = card()?.querySelector<HTMLElement>('[data-attr="advent-door-answer"]') as HTMLElement
        act(() => option.focus())
        act(() => fireEvent.click(option))
        await act(async () => {
            await jest.advanceTimersByTimeAsync(700)
        })

        expect([door(2)?.getAttribute('data-attr'), document.activeElement?.getAttribute('data-attr')]).toEqual([
            'advent-hog-2',
            'advent-door-card-close',
        ])
    })

    it.each([
        ['row', 'a desktop stage', { width: 1200, height: 830 }],
        ['column', 'a phone', { width: 375, height: 700 }],
    ])('lays the doors out as a %s on %s', (expected, _, size) => {
        renderStage(size)
        const [first, second] = [door(1), door(2)].map((element) => ({
            left: parseFloat(element?.style.left ?? ''),
            top: parseFloat(element?.style.top ?? ''),
        }))

        const shape = first.top === second.top ? 'row' : first.left === second.left ? 'column' : 'neither'

        expect(shape).toBe(expected)
    })

    it('keeps every branch label on a desktop stage short of the door it points at', () => {
        renderStage({ width: 1200, height: 830 })
        const box = (element: HTMLElement): { left: number; top: number; width: number; height: number } => ({
            left: parseFloat(element.style.left),
            top: parseFloat(element.style.top),
            width: parseFloat(element.style.width),
            height: parseFloat(element.style.height),
        })
        const doors = Array.from(document.querySelectorAll<HTMLElement>('button[data-attr^="advent-"]')).map(box)
        const pills = Array.from(document.querySelectorAll<HTMLElement>('.AdventFlowEdges__pill'))

        const reach = pills.map((pill) => {
            const { left, top } = box(pill)
            const next = doors
                .filter((door) => door.left > left && door.top <= top && top <= door.top + door.height)
                .sort((a, b) => a.left - b.left)[0]
            return left + parseFloat(pill.style.maxWidth) / 2 <= next.left
        })

        const labels = 2 * ADVENT_QUESTION_DAYS.length
        expect([pills.length, reach.filter(Boolean).length]).toEqual([labels, labels])
    })

    it('hands the opening of the last door to the caller and shows its card once the caller is done', async () => {
        jest.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
        jest.setSystemTime(new Date(2026, 11, 24, 9, 0))
        const before = Array.from({ length: ADVENT_LAST_DAY - 1 }, (_, index) => index + 1)
        seed(before, Object.fromEntries(ADVENT_QUESTION_DAYS.map((day) => [day, ADVENT_QUESTIONS[day].options[0].id])))
        let last = null as AdventFlowStepProps | null
        renderStage({ width: 1200, height: 830 }, { renderLastDoor: (step) => ((last = step), null) })

        act(() => last?.onActivate(last.node.door?.id ?? ''))
        await act(async () => {
            await jest.advanceTimersByTimeAsync(5000)
        })
        const whileOpening = [last?.isOpening, card()]
        act(() => last?.onOpened())
        await act(async () => {
            await jest.advanceTimersByTimeAsync(700)
        })

        expect([...whileOpening, last?.isOpening, card()?.getAttribute('data-open')]).toEqual([
            true,
            null,
            false,
            'true',
        ])
    })

    it.each([
        ['in view with its tab shown', true, false, 'true'],
        ['out of view', false, false, 'false'],
        ['in view in a hidden tab', true, true, 'false'],
    ])("wakes today's glow only while the stage is %s", (_, isIntersecting, isHidden, awake) => {
        let reportView: (isIntersecting: boolean) => void = () => undefined
        jest.mocked(IntersectionObserver).mockImplementation((callback) => {
            const observer: IntersectionObserver = {
                root: null,
                rootMargin: '',
                scrollMargin: '',
                thresholds: [],
                observe: () => undefined,
                unobserve: () => undefined,
                disconnect: () => undefined,
                takeRecords: () => [],
            }
            reportView = (isIntersecting) => callback([{ isIntersecting } as IntersectionObserverEntry], observer)
            return observer
        })
        renderStage({ width: 1200, height: 830 })
        jest.spyOn(document, 'hidden', 'get').mockReturnValue(isHidden)

        act(() => reportView(isIntersecting))
        act(() => void document.dispatchEvent(new Event('visibilitychange')))

        expect(document.querySelector('[data-attr="advent-stage"]')?.getAttribute('data-awake')).toBe(awake)
    })

    it('lets the caller draw the last door and emphasize edges', () => {
        renderStage(
            { width: 1200, height: 830 },
            {
                renderLastDoor: ({ node }) => <span data-attr="advent-last-door">{node.door?.day}</span>,
                isEdgeEmphasized: (edge) => edge.target === 'door-1',
            }
        )

        expect(door(24)).toBeNull()
        expect(document.querySelector('[data-attr="advent-last-door"]')?.textContent).toBe('24')
        expect(
            Array.from(document.querySelectorAll('[data-emphasized="true"]')).map((edge) =>
                edge.getAttribute('data-edge')
            )
        ).toEqual(['trigger>door-1'])
    })
})
