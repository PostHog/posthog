import { act, fireEvent, render, RenderResult } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
    let measure: jest.SpyInstance
    let stage: RenderResult | null
    const bodiesOverflow = { current: false }

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
        jest.spyOn(posthog, 'capture').mockImplementation()
        measure = jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
        initKeaTests()
        await expectLogic(userLogic).toFinishAllListeners()
        userLogic.actions.loadUserSuccess({ ...userLogic.values.user, uuid: UUID } as UserType)
        stage = null
        bodiesOverflow.current = false
        const bodyHeight = (scrolled: number, element: Element): number =>
            bodiesOverflow.current && element.classList.contains('AdventCard__body') ? scrolled : 0
        jest.spyOn(Element.prototype, 'scrollHeight', 'get').mockImplementation(function (this: Element) {
            return bodyHeight(400, this)
        })
        jest.spyOn(Element.prototype, 'clientHeight', 'get').mockImplementation(function (this: Element) {
            return bodyHeight(120, this)
        })
    })

    afterEach(() => {
        stage?.unmount()
        adventCalendarLogic.findMounted()?.unmount()
        jest.restoreAllMocks()
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

    it('slides the card out over a closed door on hover, not over an open one, and pins it as a dialog named by its title on a click until Escape', () => {
        seed([1, 2], { 2: 'tim' })
        renderStage({ width: 1200, height: 830 })

        act(() => fireEvent.mouseEnter(door(4) as HTMLElement))
        const face = card()?.querySelector<HTMLElement>('.AdventCard__door')
        expect([card()?.textContent, face?.querySelector('svg'), card()?.getAttribute('role')]).toEqual([
            expect.stringContaining('Opens December 4.'),
            null,
            null,
        ])
        act(() => fireEvent.mouseLeave(door(4) as HTMLElement))
        waitForTheCardToClose()
        act(() => fireEvent.mouseEnter(door(2) as HTMLElement))
        expect(card()).toBeNull()

        act(() => fireEvent.click(door(2) as HTMLElement))
        const name = document.getElementById(card()?.getAttribute('aria-labelledby') ?? '')?.textContent
        expect([
            card()?.querySelector('[data-attr="advent-door-card-close"]'),
            card()?.getAttribute('role'),
            name,
        ]).toEqual([expect.anything(), 'dialog', 'Tim Glaser'])
        act(() => fireEvent.keyDown(window, { key: 'Escape' }))
        waitForTheCardToClose()
        expect(card()).toBeNull()
    })

    it.each([
        ['open', [1, 2, 24]],
        ['locked', [1, 2]],
    ])('names every pinned card by an element on the stage, with door 24 %s', (_, opened) => {
        seed(opened, { 2: 'tim' })
        renderStage({ width: 1200, height: 830 })

        const names = Array.from({ length: 24 }, (_, index) => {
            act(() => fireEvent.click(door(index + 1) as HTMLElement))
            act(() => jest.advanceTimersByTime(2600))
            const label = card()?.getAttribute('aria-labelledby')
            const name = [card()?.getAttribute('role'), document.getElementById(label ?? '')?.textContent?.trim()]
            act(() => fireEvent.keyDown(window, { key: 'Escape' }))
            waitForTheCardToClose()
            return name
        })

        expect(names).toEqual(Array.from({ length: 24 }, () => ['dialog', expect.stringMatching(/\S/)]))
    })

    it('opens the hovered ready door on a click, hides its card and ignores the next door during the opening, then pins its card on the hoggy behind it', async () => {
        jest.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
        seed([1, 2], { 2: 'tim' })
        renderStage({ width: 1200, height: 830 })

        act(() => fireEvent.mouseEnter(door(3) as HTMLElement))
        act(() => fireEvent.click(card()?.querySelector('.AdventCard__face') as HTMLElement))
        const atClick = card()
        act(() => fireEvent.click(door(4) as HTMLElement))
        await act(async () => {
            await jest.advanceTimersByTimeAsync(2300)
        })
        const whileOpening = [atClick, door(3)?.getAttribute('data-attr'), card()]
        for (const step of [200, 100]) {
            await act(async () => {
                await jest.advanceTimersByTimeAsync(step)
            })
        }

        expect(whileOpening).toEqual([null, 'advent-hog-3', null])
        const name = document.getElementById(card()?.getAttribute('aria-labelledby') ?? '')?.textContent
        expect([card()?.getAttribute('data-open'), name]).toEqual(['true', 'Reading'])
        act(() => fireEvent.click(card()?.querySelector('[data-attr="advent-door-card-close"]') as HTMLElement))
        waitForTheCardToClose()
        expect(card()).toBeNull()
    })

    it.each([
        ['Close', 2, '[data-attr="advent-door-card-close"]'],
        ['the tip link', 1, '[data-attr="advent-tip-link"]'],
    ])(
        'moves focus into a pinned card, makes the closing card inert, and moves focus back to its door when Escape closes it from %s',
        (_, day, focused) => {
            seed([1, 2], { 2: 'tim' })
            renderStage({ width: 375, height: 700 })

            act(() => (door(day) as HTMLElement).focus())
            act(() => fireEvent.click(door(day) as HTMLElement))
            const focusInCard = document.activeElement?.getAttribute('data-attr')
            act(() => (document.querySelector(focused) as HTMLElement).focus())
            act(() => fireEvent.keyDown(window, { key: 'Escape' }))
            const isClosingCardInert = card()?.hasAttribute('inert')
            waitForTheCardToClose()

            expect([focusInCard, isClosingCardInert, document.activeElement === door(day)]).toEqual([
                'advent-door-card-close',
                true,
                true,
            ])
        }
    )

    type CardSetup =
        | 'pinned'
        | 'overflowing'
        | 'overflowing at pin'
        | 'overflowing after pin'
        | 'fitting after pin'
        | 'answered'
        | 'hovered'
    type Key = 'Tab' | 'Shift+Tab' | 'Escape' | 'Enter' | 'pointer down'
    const CONTROLS: Record<string, string> = {
        Close: '[data-attr="advent-door-card-close"]',
        'the face': '.AdventCard__face',
        'the link': '[data-attr="advent-tip-link"]',
        'the body': '.AdventCard__body',
        'the first answer': '[data-attr="advent-door-answer"]',
        'the last answer': '[data-attr="advent-door-answer"]:last-of-type',
    }
    const [CLOSE, FACE, LINK, BODY, FIRST_ANSWER, LAST_ANSWER] = Object.keys(CONTROLS)

    it.each<
        [string, Key, string | number, string | number, 'pinned' | 'hover' | 'closed', number, number[], CardSetup]
    >([
        ['day 1 with a link', 'Tab', CLOSE, LINK, 'pinned', 1, [1, 2], 'pinned'],
        ['day 1 with a link', 'Tab', LINK, CLOSE, 'pinned', 1, [1, 2], 'pinned'],
        ['day 1 with a link', 'Shift+Tab', LINK, CLOSE, 'pinned', 1, [1, 2], 'pinned'],
        ['day 1 with a link', 'Shift+Tab', CLOSE, LINK, 'pinned', 1, [1, 2], 'pinned'],
        ['day 1 with a link', 'Escape', LINK, 1, 'closed', 1, [1, 2], 'pinned'],
        ['day 1 with a link', 'Enter', CLOSE, 1, 'closed', 1, [1, 2], 'pinned'],
        ['day 1 with a link and a body that overflows', 'Tab', LINK, CLOSE, 'pinned', 1, [1, 2], 'overflowing'],
        ['day 2 without a link', 'Tab', CLOSE, CLOSE, 'pinned', 2, [1, 2], 'pinned'],
        ['day 2 without a link', 'Shift+Tab', CLOSE, CLOSE, 'pinned', 2, [1, 2], 'pinned'],
        ['day 2 without a link', 'Escape', CLOSE, 2, 'closed', 2, [1, 2], 'pinned'],
        ['day 2 with a body that overflows', 'Tab', CLOSE, BODY, 'pinned', 2, [1, 2], 'overflowing'],
        ['day 2 with a body that overflows', 'Tab', BODY, CLOSE, 'pinned', 2, [1, 2], 'overflowing'],
        ['day 2 with a body that overflows', 'Shift+Tab', CLOSE, BODY, 'pinned', 2, [1, 2], 'overflowing'],
        ['day 2 with a body that overflows', 'Escape', BODY, 2, 'closed', 2, [1, 2], 'overflowing'],
        [
            'day 2 with a body that overflows when it pins',
            'Tab',
            CLOSE,
            BODY,
            'pinned',
            2,
            [1, 2],
            'overflowing at pin',
        ],
        [
            'day 2 with a body that overflows when it pins',
            'Shift+Tab',
            CLOSE,
            BODY,
            'pinned',
            2,
            [1, 2],
            'overflowing at pin',
        ],
        [
            'day 2 with a body that overflows once the card is pinned',
            'Tab',
            CLOSE,
            BODY,
            'pinned',
            2,
            [1, 2],
            'overflowing after pin',
        ],
        ['day 2 with a body that fits again', 'Tab', CLOSE, CLOSE, 'pinned', 2, [1, 2], 'fitting after pin'],
        ['day 2 with a body that fits again', 'Shift+Tab', CLOSE, CLOSE, 'pinned', 2, [1, 2], 'fitting after pin'],
        ['day 24', 'Tab', LINK, CLOSE, 'pinned', 24, [1, 2, 24], 'pinned'],
        ['day 24', 'Shift+Tab', CLOSE, LINK, 'pinned', 24, [1, 2, 24], 'pinned'],
        ['a poll before an answer', 'Tab', CLOSE, FIRST_ANSWER, 'pinned', 2, [1], 'pinned'],
        ['a poll before an answer', 'Tab', LAST_ANSWER, CLOSE, 'pinned', 2, [1], 'pinned'],
        ['a poll before an answer', 'Shift+Tab', CLOSE, LAST_ANSWER, 'pinned', 2, [1], 'pinned'],
        ['a poll before an answer', 'Escape', LAST_ANSWER, 2, 'closed', 2, [1], 'pinned'],
        ['a poll after a keyboard answer', 'Tab', CLOSE, CLOSE, 'pinned', 2, [1], 'answered'],
        ['a poll after a keyboard answer', 'Shift+Tab', CLOSE, CLOSE, 'pinned', 2, [1], 'answered'],
        ['a hover-only card', 'Tab', 24, CLOSE, 'pinned', 4, [1, 2], 'hovered'],
        ['a hover-only card', 'pointer down', FACE, FACE, 'hover', 4, [1, 2], 'hovered'],
        ['a hover-only card', 'Escape', FACE, 4, 'closed', 4, [1, 2], 'hovered'],
    ])(
        'on %s, %s from %s moves focus to %s and leaves the card %s',
        async (_, key, from, focusTarget, cardState, day, opened, setup) => {
            jest.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
            const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
            seed(opened, opened.includes(2) ? { 2: 'tim' } : {})
            renderStage({ width: 1200, height: 830 })
            const target = (selector: string | number): HTMLElement | null =>
                typeof selector === 'number'
                    ? door(selector)
                    : (card()?.querySelector<HTMLElement>(CONTROLS[selector]) ?? null)

            bodiesOverflow.current = setup === 'overflowing at pin' || setup === 'fitting after pin'
            if (setup === 'hovered') {
                act(() => fireEvent.mouseEnter(door(day) as HTMLElement))
            } else {
                act(() => fireEvent.click(door(day) as HTMLElement))
            }
            if (setup === 'answered') {
                const option = target(FIRST_ANSWER) as HTMLElement
                act(() => option.focus())
                act(() => fireEvent.click(option))
                await act(async () => {
                    await jest.advanceTimersByTimeAsync(700)
                })
            }
            const body = target(BODY) as HTMLElement
            if (setup === 'overflowing after pin' || setup === 'fitting after pin') {
                bodiesOverflow.current = setup === 'overflowing after pin'
            }
            if (setup === 'overflowing') {
                Object.defineProperties(body, { scrollHeight: { value: 400 }, clientHeight: { value: 120 } })
                body.tabIndex = body.querySelector('button, a[href]') ? -1 : 0
            }
            const start = target(from) as HTMLElement
            act(() => start.focus())
            if (key === 'pointer down') {
                act(() => {
                    fireEvent.keyDown(window, { key: 'Tab' })
                    fireEvent.pointerDown(start)
                    start.blur()
                    start.focus()
                })
            } else if (key === 'Tab' || key === 'Shift+Tab') {
                await user.tab({ shift: key === 'Shift+Tab' })
            } else {
                await user.keyboard(`{${key}}`)
            }
            waitForTheCardToClose()

            const state = !card() ? 'closed' : target(CLOSE) ? 'pinned' : 'hover'
            expect([document.activeElement === target(focusTarget), state]).toEqual([true, cardState])
        }
    )

    it.each([
        ['a pinned card', 2, true],
        ['the card of a door still opening', 3, false],
    ])('closes %s when the phone column scrolls under it', async (_, day, isPinnedBeforeScroll) => {
        jest.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
        seed([1, 2], { 2: 'tim' })
        renderStage({ width: 375, height: 700 })

        act(() => fireEvent.click(door(day) as HTMLElement))
        const isPinned = !!card()
        act(() => fireEvent.scroll(document.querySelector('.AdventFlowStage__track') as HTMLElement))
        await act(async () => {
            await jest.advanceTimersByTimeAsync(2600)
        })

        expect([isPinned, card()]).toEqual([isPinnedBeforeScroll, null])
    })

    it.each([
        ['day 1, whose overflowing body holds a link', 1, true],
        ['day 2, whose body fits', 2, false],
    ])('gives the body of the pinned card for %s no tab stop', async (_, day, overflows) => {
        jest.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
        const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
        seed([1, 2], { 2: 'tim' })
        bodiesOverflow.current = overflows
        renderStage({ width: 1200, height: 830 })

        act(() => fireEvent.click(door(day) as HTMLElement))
        await user.tab()

        expect(card()?.querySelector('.AdventCard__body')?.getAttribute('tabindex')).toBeNull()
    })

    it.each([
        ['under reduced motion', true, 'advent-door-card-close'],
        ['while its door opens', false, 'advent-hog-2'],
    ])(
        'keeps focus on the answered door or its pinned card after a keyboard answer %s',
        async (_, reducesMotion, focusAtOnce) => {
            jest.spyOn(window, 'matchMedia').mockReturnValue({ matches: reducesMotion } as MediaQueryList)
            seed([1], {})
            renderStage({ width: 1200, height: 830 })

            act(() => fireEvent.click(door(2) as HTMLElement))
            const option = card()?.querySelector<HTMLElement>('[data-attr="advent-door-answer"]') as HTMLElement
            act(() => option.focus())
            act(() => fireEvent.click(option))
            await act(async () => {
                await jest.advanceTimersByTimeAsync(100)
            })
            const focusedAtOnce = document.activeElement?.getAttribute('data-attr')
            await act(async () => {
                await jest.advanceTimersByTimeAsync(2600)
            })

            expect([
                door(2)?.getAttribute('data-attr'),
                focusedAtOnce,
                document.activeElement?.getAttribute('data-attr'),
            ]).toEqual(['advent-hog-2', focusAtOnce, 'advent-door-card-close'])
        }
    )

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
