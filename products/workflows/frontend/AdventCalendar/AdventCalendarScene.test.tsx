import { act, render, screen } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AdventCalendarScene } from './AdventCalendarScene'

type ReloadStatus = 'loaded' | 'error'

describe('AdventCalendarScene', () => {
    let finishFlagLoad: (status: ReloadStatus) => Promise<void>
    const originalFeatureFlags = posthog.featureFlags

    beforeEach(() => {
        window.localStorage.clear()
        jest.useFakeTimers()
        initKeaTests()
        appLogic.mount()
        router.actions.push(urls.workflowsAdventCalendar())
        let resolveLoad: (result: { status: ReloadStatus }) => void = () => {}
        const reloadFeatureFlagsAsync = (): Promise<{ status: ReloadStatus }> =>
            new Promise((resolve) => {
                resolveLoad = resolve
            })
        finishFlagLoad = async (status) => {
            await act(async () => resolveLoad({ status }))
        }
        Object.assign(posthog, { featureFlags: { reloadFeatureFlagsAsync } })
    })

    afterEach(() => {
        jest.useRealTimers()
        Object.assign(posthog, { featureFlags: originalFeatureFlags })
    })

    const pathname = (): string => router.values.location.pathname
    const showsCalendar = (): boolean => !!screen.queryByText('THE WORKFLOWS ADVENT CALENDAR')
    const showsSpinner = (): boolean => !!document.querySelector('.SpinnerOverlay')
    const setCalendarFlag = (enabled: boolean): void =>
        act(() => featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: enabled }))

    it.each([
        ['the shared link', urls.workflowsAdventCalendar()],
        ['an encoded path', urls.workflowsAdventCalendar().replace('advent', '%61dvent')],
    ])('sends a visitor without the calendar on %s to Workflows once a fresh flag load agrees', async (_, url) => {
        router.actions.push(url)
        const { unmount } = render(<AdventCalendarScene />)
        setCalendarFlag(false)
        expect({ pathname: pathname(), showsSpinner: showsSpinner() }).toEqual({
            pathname: expect.stringMatching(/\/workflows\/(advent|%61dvent)$/),
            showsSpinner: true,
        })

        await finishFlagLoad('loaded')

        expect(pathname()).toMatch(/\/workflows$/)
        unmount()
    })

    it.each([
        ['another scene', urls.insights(), /\/insights$/],
        [
            'the calendar written another way',
            urls.workflowsAdventCalendar().replace('advent', '%61dvent'),
            /\/workflows$/,
        ],
    ])('settles a visitor who moved to %s during the flag load', async (_, destination, expected) => {
        const { unmount } = render(<AdventCalendarScene />)
        setCalendarFlag(false)
        act(() => router.actions.push(destination))

        await finishFlagLoad('loaded')

        expect(pathname()).toMatch(expected)
        unmount()
    })

    it('leaves a visitor who navigated on before the flag turned off where they went', async () => {
        setCalendarFlag(true)
        const { unmount } = render(<AdventCalendarScene />)
        act(() => router.actions.push(urls.insights()))
        setCalendarFlag(false)

        await finishFlagLoad('loaded')

        expect(pathname()).toMatch(/\/insights$/)
        unmount()
    })

    it('keeps a visitor whose early flags missed the calendar but the fresh load has it', async () => {
        const { unmount } = render(<AdventCalendarScene />)
        setCalendarFlag(false)

        setCalendarFlag(true)
        await finishFlagLoad('loaded')

        expect({ pathname: pathname(), showsCalendar: showsCalendar() }).toEqual({
            pathname: expect.stringMatching(/\/workflows\/advent$/),
            showsCalendar: true,
        })
        unmount()
    })

    it('sends a visitor to Workflows when flags time out and the flag load fails', async () => {
        const { unmount } = render(<AdventCalendarScene />)
        act(() => jest.advanceTimersByTime(3000))

        await finishFlagLoad('error')

        expect(pathname()).toMatch(/\/workflows$/)
        unmount()
    })

    it('keeps a visitor with the calendar on it', async () => {
        setCalendarFlag(true)
        const { unmount } = render(<AdventCalendarScene />)

        expect({ pathname: pathname(), showsCalendar: showsCalendar() }).toEqual({
            pathname: expect.stringMatching(/\/workflows\/advent$/),
            showsCalendar: true,
        })
        unmount()
    })
})
