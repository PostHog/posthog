import { act, render } from '@testing-library/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AdventCalendarScene } from './AdventCalendarScene'

describe('AdventCalendarScene', () => {
    beforeEach(() => {
        initKeaTests()
        appLogic.mount()
        router.actions.push(urls.workflowsAdventCalendar())
    })

    it('sends a visitor without the calendar to Workflows once their flags are in', () => {
        const { unmount } = render(<AdventCalendarScene />)
        expect(router.values.location.pathname).toMatch(/\/workflows\/advent$/)

        act(() => featureFlagLogic.actions.setFeatureFlags([], {}))

        expect(router.values.location.pathname).toMatch(/\/workflows$/)
        unmount()
    })

    it('keeps a visitor on the calendar while their flags are still loading', () => {
        const { unmount } = render(<AdventCalendarScene />)
        act(() => appLogic.actions.ignoreFeatureFlags())

        expect(router.values.location.pathname).toMatch(/\/workflows\/advent$/)
        unmount()
    })

    it('keeps a visitor with the calendar on it', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: true })

        const { unmount } = render(<AdventCalendarScene />)

        expect(router.values.location.pathname).toMatch(/\/workflows\/advent$/)
        unmount()
    })
})
