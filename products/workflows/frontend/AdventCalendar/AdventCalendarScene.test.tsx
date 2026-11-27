import { act, cleanup, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AdventCalendarScene } from './AdventCalendarScene'

describe('AdventCalendarScene', () => {
    beforeEach(() => {
        window.localStorage.clear()
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    const openCalendar = ({
        cachedFlags = {} as Record<string, boolean>,
        url = urls.workflowsAdventCalendar(),
    } = {}): void => {
        window.localStorage.setItem('lib.logic.featureFlagLogic.featureFlags', JSON.stringify(cachedFlags))
        initKeaTests()
        appLogic.mount()
        router.actions.push(url)
        render(<AdventCalendarScene />)
    }

    const pathname = (): string => router.values.location.pathname
    const screenState = (): { calendar: boolean; spinner: boolean } => ({
        calendar: !!screen.queryByText('THE WORKFLOWS ADVENT CALENDAR'),
        spinner: !!document.querySelector('.SpinnerOverlay'),
    })
    const flagsArrive = (calendar: boolean): void =>
        act(() => featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: calendar }))
    const flagsTimeOut = (): void => act(() => jest.advanceTimersByTime(3000))

    it('shows the calendar to a visitor with the flag', () => {
        openCalendar()
        flagsArrive(true)

        expect({ pathname: pathname(), ...screenState() }).toEqual({
            pathname: expect.stringMatching(/\/workflows\/advent$/),
            calendar: true,
            spinner: false,
        })
    })

    it.each([
        ['their flags come back off', urls.workflowsAdventCalendar(), () => flagsArrive(false)],
        ['their flags time out', urls.workflowsAdventCalendar(), flagsTimeOut],
        ['the link is encoded', urls.workflowsAdventCalendar().replace('advent', '%61dvent'), () => flagsArrive(false)],
    ])('sends a visitor without the calendar to Workflows when %s', (_, url, settleFlags) => {
        openCalendar({ url })
        settleFlags()

        expect(pathname()).toMatch(/\/workflows$/)
    })

    it('shows a spinner and no calendar while flags are unknown', () => {
        openCalendar()

        expect({ pathname: pathname(), ...screenState() }).toEqual({
            pathname: expect.stringMatching(/\/workflows\/advent$/),
            calendar: false,
            spinner: true,
        })
    })

    it('leaves a visitor who moved on before flags arrived where they went', () => {
        openCalendar()
        act(() => router.actions.push(urls.insights()))
        flagsArrive(false)

        expect(pathname()).toMatch(/\/insights$/)
    })

    it('shows the calendar from cached flags when the flag request is blocked', () => {
        openCalendar({ cachedFlags: { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: true } })
        flagsTimeOut()

        expect({ pathname: pathname(), ...screenState() }).toEqual({
            pathname: expect.stringMatching(/\/workflows\/advent$/),
            calendar: true,
            spinner: false,
        })
    })
})
