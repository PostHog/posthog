import { act, fireEvent, render, within } from '@testing-library/react'
import { NodeProps, ReactFlowProvider } from '@xyflow/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { adventCalendarLogic } from './adventCalendarLogic'
import { AdventDoorCard } from './AdventDoorCard'
import { AdventDoorNode, AdventDoorNodeType } from './AdventDoorNode'
import { AdventShareButton } from './AdventShareButton'
import { AdventStage } from './AdventStage'

const UUID = '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01'

describe('AdventStage', () => {
    let capture: jest.SpyInstance
    let measure: jest.SpyInstance

    beforeEach(async () => {
        jest.useFakeTimers({ now: new Date(2026, 11, 3, 9, 0), advanceTimers: true })
        window.localStorage.clear()
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
        measure = jest
            .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
            .mockReturnValue({ width: 1200, height: 800 } as DOMRect)
        initKeaTests()
        await expectLogic(userLogic).toFinishAllListeners()
        userLogic.actions.loadUserSuccess({
            ...userLogic.values.user,
            uuid: UUID,
        } as UserType)
    })

    afterEach(() => {
        measure.mockRestore()
        capture.mockRestore()
        jest.useRealTimers()
    })

    it('takes the doors and the share button out of reach while a reveal runs, and gives them back after', () => {
        window.localStorage.setItem(
            'workflows-advent-calendar-progress',
            JSON.stringify({ [UUID]: { opened: [1, 2], answers: { 2: 'tim' } } })
        )
        const logic = adventCalendarLogic()
        logic.mount()
        const { container, unmount } = render(
            <>
                <AdventShareButton />
                <AdventStage />
            </>
        )
        const reach = (): { doors: boolean; share: boolean } => ({
            doors: !container.querySelector('.AdventStage__workflow')?.hasAttribute('inert'),
            share: container.querySelector('[data-attr="advent-share"]')?.getAttribute('aria-disabled') === 'false',
        })

        expect(reach()).toEqual({ doors: true, share: true })

        const doorThree = logic.values.graph.doors.find((door) => door.day === 3 && door.status === 'ready')!
        act(() => logic.actions.activateDoor(doorThree.id))
        expect(reach()).toEqual({ doors: false, share: false })

        act(() => logic.actions.finishReveal())
        expect(reach()).toEqual({ doors: true, share: true })

        unmount()
        logic.unmount()
    })

    it('lays out a locked door card the same in the top and bottom rows, with the weekday and date on single lines', () => {
        const logic = adventCalendarLogic()
        logic.mount()
        const noop = (): void => {}
        const cardOf = (day: number): HTMLElement => {
            const door = logic.values.graph.doors.find((candidate) => candidate.day === day)!
            const { container } = render(
                <AdventDoorCard
                    door={door}
                    face={{ left: 500, top: door.row === 2 ? 600 : 100, size: 56, zoom: 1 }}
                    stage={{ width: 1200, height: 720 }}
                    isOpen
                    isPinned={false}
                    onPin={noop}
                    onAnswer={noop}
                    onTipClick={noop}
                    onClose={noop}
                    onMouseEnter={noop}
                    onMouseLeave={noop}
                />
            )
            return container.querySelector<HTMLElement>('[data-attr="advent-door-card"]')!
        }
        const layout = (card: HTMLElement): string[] => [
            card.className,
            ...Array.from(card.querySelectorAll('*')).map((node) => node.getAttribute('class') ?? node.tagName),
        ]
        const top = cardOf(4)
        const bottom = cardOf(21)

        expect(logic.values.graph.doors.find((door) => door.day === 21)?.row).toBe(2)
        expect(layout(bottom)).toEqual(layout(top))
        expect(bottom.textContent).toBe('21MondayCoffee or teaOpens December 21.')
        expect(top.textContent).toBe('4FridayLockedOpens December 4.')

        logic.unmount()
    })

    it.each([
        [3, 'Door 3, ready', '3Today'],
        [4, 'Door 4, opens December 4', '4'],
        [21, 'Door 21, opens December 21', '21Coffee or tea?'],
    ])('names door %s "%s" and shows "%s" on the stage', async (day, name, shown) => {
        window.localStorage.setItem(
            'workflows-advent-calendar-progress',
            JSON.stringify({ [UUID]: { opened: [1, 2], answers: { 2: 'tim' } } })
        )
        const logic = adventCalendarLogic()
        logic.mount()
        const door = logic.values.graph.doors.find((candidate) => candidate.day === day)!
        const props = { data: { door, isSelected: false, isToday: day === 3, isOpening: false } }
        const { container } = render(
            <ReactFlowProvider>
                <AdventDoorNode {...(props as NodeProps<AdventDoorNodeType>)} />
            </ReactFlowProvider>
        )

        expect(container.querySelector(`[data-attr="advent-door-${day}"]`)?.getAttribute('aria-label')).toBe(name)
        expect(container.textContent).toBe(shown)

        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
    })

    it('shows the share of the pick on the plaque and both shares in the door card', async () => {
        window.localStorage.setItem(
            'workflows-advent-calendar-progress',
            JSON.stringify({ [UUID]: { opened: [1, 2], answers: { 2: 'tim' } } })
        )
        useMocks({
            get: {
                '/api/projects/:team_id/workflow_advent_calendar/results/': {
                    questions: [
                        {
                            day: 2,
                            answer: 'tim',
                            shares: [
                                { option: 'james', share: 38 },
                                { option: 'tim', share: 62 },
                            ],
                        },
                    ],
                },
            },
        })
        const logic = adventCalendarLogic()
        logic.mount()
        const { container, findByText, unmount } = render(<AdventStage />)

        const plaque = within(container.querySelector<HTMLElement>('[data-attr="advent-door-pick"]')!)
        expect(await plaque.findByText('62% agree')).toBeTruthy()

        fireEvent.click(container.querySelector('[data-attr="advent-hog-2"]')!)
        await findByText('How people answered')
        const shares = container.querySelector('[data-attr="advent-door-shares"]')?.textContent
        expect(shares).toBe('How people answeredJames38%Tim62%')

        unmount()
        logic.unmount()
    })
})
