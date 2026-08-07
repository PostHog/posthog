import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { HeatmapsWarnings } from './HeatmapsWarnings'

describe('HeatmapsWarnings', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    const setOptIn = (heatmaps_opt_in: boolean | undefined): void => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, heatmaps_opt_in })
    }

    const bannerText = /Heatmap collection is turned off/

    // The bug this guards: the banner fired on the capture setting alone, so it sat on top of a
    // working heatmap whenever data came from autocapture clickmaps or the SDK enable_heatmaps
    // override. It must stay hidden whenever the view has data, regardless of the setting.
    it.each([
        ['off with an empty view', false, false, true],
        ['off but the view has data', false, true, false],
        ['never set with an empty view', undefined, false, true],
        ['on', true, false, false],
        ['on with data', true, true, false],
    ] as const)('%s', (_name, heatmapsOptIn, viewHasData, expectVisible) => {
        setOptIn(heatmapsOptIn)
        render(
            <Provider>
                <HeatmapsWarnings viewHasData={viewHasData} />
            </Provider>
        )

        if (expectVisible) {
            expect(screen.getByText(bannerText)).toBeInTheDocument()
        } else {
            expect(screen.queryByText(bannerText)).not.toBeInTheDocument()
        }
    })
})
