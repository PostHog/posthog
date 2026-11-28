import { render } from '@testing-library/react'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { AdventEntry } from './AdventEntry'

const FLAG = FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR

type Visit = { flagsRequest: 'loaded' | 'blocked'; page: boolean | 'left out'; sdkFlag: boolean }

function openThePage({ flagsRequest, page, sdkFlag }: Visit): void {
    window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
        distinctID: 'person-1',
        featureFlags: page === 'left out' ? {} : { [FLAG]: page },
    }
    if (flagsRequest === 'blocked') {
        window.POSTHOG_GLOBAL_ERRORS = { onFeatureFlagsLoadError: true }
        jest.mocked(posthog.get_property).mockImplementation((key) =>
            key === '$feature_flag_errors' ? ['connection_error'] : undefined
        )
    } else {
        window.POSTHOG_FEATURE_FLAGS_LOADED = true
    }
    featureFlagLogic.actions.setFeatureFlags(sdkFlag ? [FLAG] : [], sdkFlag ? { [FLAG]: true } : {})
}

describe('AdventEntry', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        delete window.POSTHOG_GLOBAL_ERRORS
        delete window.POSTHOG_FEATURE_FLAGS_LOADED
        jest.mocked(posthog.get_property).mockReset()
    })

    it.each<[string, Visit, boolean]>([
        ['hides the card while the flag is off', { flagsRequest: 'loaded', page: 'left out', sdkFlag: false }, false],
        ['shows the card while the flag is on', { flagsRequest: 'loaded', page: true, sdkFlag: true }, true],
        [
            'shows the card in a blocked browser when the page decides on',
            { flagsRequest: 'blocked', page: true, sdkFlag: false },
            true,
        ],
        [
            'hides the card in a blocked browser when the page decides off',
            { flagsRequest: 'blocked', page: false, sdkFlag: true },
            false,
        ],
    ])('%s', (_, visit, shown) => {
        openThePage(visit)

        const { container } = render(<AdventEntry />)

        expect(container.querySelector('[data-attr="advent-entry-card"]') !== null).toBe(shown)
    })
})
