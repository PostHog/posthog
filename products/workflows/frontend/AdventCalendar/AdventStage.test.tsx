import { act, render } from '@testing-library/react'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { adventCalendarLogic } from './adventCalendarLogic'
import { AdventStage } from './AdventStage'

describe('AdventStage', () => {
    let capture: jest.SpyInstance
    let measure: jest.SpyInstance

    beforeEach(() => {
        jest.useFakeTimers({ now: new Date(2026, 11, 3, 9, 0) })
        window.localStorage.clear()
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
        measure = jest
            .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
            .mockReturnValue({ width: 1200, height: 800 } as DOMRect)
        initKeaTests()
        userLogic.actions.loadUserSuccess({
            ...userLogic.values.user,
            uuid: '0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01',
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
})
