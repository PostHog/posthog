import { act, fireEvent, render, within } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { adventCalendarLogic } from './adventCalendarLogic'
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

    it('takes the doors out of keyboard reach while a reveal runs, and gives them back after', () => {
        const logic = adventCalendarLogic()
        logic.mount()
        const { container, unmount } = render(<AdventStage />)
        const isInert = (): boolean | undefined =>
            container.querySelector('.AdventStage__workflow')?.hasAttribute('inert')

        expect(isInert()).toBe(false)

        act(() => logic.actions.activateDoor('door-1'))
        expect(isInert()).toBe(true)

        act(() => logic.actions.finishReveal())
        expect(isInert()).toBe(false)

        unmount()
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
