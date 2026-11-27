import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { adventCalendarAccess } from './adventCalendarAccess'

const FLAG = FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR

type PageFlags = Record<string, boolean | string> | null | 'no page object'

type Visit = {
    loadFailed: boolean
    freshFlag: boolean | undefined
    pageFlags: PageFlags
    liveFlags: FeatureFlagsSet
    receivedFeatureFlags: boolean
}

describe('adventCalendarAccess', () => {
    afterEach(() => {
        delete window.POSTHOG_GLOBAL_ERRORS
        delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        jest.mocked(posthog.getFeatureFlag).mockReset()
    })

    it.each<[string, Visit, boolean | undefined]>([
        [
            'a successful load shows the live flag on',
            {
                loadFailed: false,
                freshFlag: true,
                pageFlags: { [FLAG]: false },
                liveFlags: { [FLAG]: true },
                receivedFeatureFlags: true,
            },
            true,
        ],
        [
            'a successful load with the flag off wins over a page decision on',
            {
                loadFailed: false,
                freshFlag: false,
                pageFlags: { [FLAG]: true },
                liveFlags: { [FLAG]: false },
                receivedFeatureFlags: true,
            },
            false,
        ],
        [
            'a successful retry after a failed load wins over a page decision on',
            {
                loadFailed: true,
                freshFlag: false,
                pageFlags: { [FLAG]: true },
                liveFlags: { [FLAG]: false },
                receivedFeatureFlags: true,
            },
            false,
        ],
        [
            'a failed load shows the page decision on',
            {
                loadFailed: true,
                freshFlag: undefined,
                pageFlags: { [FLAG]: true },
                liveFlags: {},
                receivedFeatureFlags: true,
            },
            true,
        ],
        [
            'a failed load shows the page decision off over a stored flag on',
            {
                loadFailed: true,
                freshFlag: undefined,
                pageFlags: { [FLAG]: false },
                liveFlags: { [FLAG]: true },
                receivedFeatureFlags: true,
            },
            false,
        ],
        [
            'nothing known yet is unknown',
            {
                loadFailed: false,
                freshFlag: undefined,
                pageFlags: { [FLAG]: true },
                liveFlags: {},
                receivedFeatureFlags: false,
            },
            undefined,
        ],
        [
            'a failed load on a page without the identity object keeps the stored flag',
            {
                loadFailed: true,
                freshFlag: undefined,
                pageFlags: 'no page object',
                liveFlags: { [FLAG]: true },
                receivedFeatureFlags: true,
            },
            true,
        ],
        [
            'a failed load on a page without flag decisions keeps the stored flag',
            {
                loadFailed: true,
                freshFlag: undefined,
                pageFlags: null,
                liveFlags: { [FLAG]: true },
                receivedFeatureFlags: true,
            },
            true,
        ],
        [
            'a failed load on a page that left the flag out keeps the stored flag',
            {
                loadFailed: true,
                freshFlag: undefined,
                pageFlags: { 'some-other-flag': true },
                liveFlags: {},
                receivedFeatureFlags: true,
            },
            false,
        ],
        [
            'a failed load ignores a page value that is not a boolean',
            {
                loadFailed: true,
                freshFlag: undefined,
                pageFlags: { [FLAG]: 'true' },
                liveFlags: {},
                receivedFeatureFlags: true,
            },
            false,
        ],
    ])('%s', (_name, { loadFailed, freshFlag, pageFlags, liveFlags, receivedFeatureFlags }, expected) => {
        if (loadFailed) {
            window.POSTHOG_GLOBAL_ERRORS = { onFeatureFlagsLoadError: true }
        }
        if (pageFlags !== 'no page object') {
            window.POSTHOG_USER_IDENTITY_WITH_FLAGS = { distinctID: 'person-1', featureFlags: pageFlags }
        }
        jest.mocked(posthog.getFeatureFlag).mockImplementation((key, options) =>
            key === FLAG && options?.fresh ? freshFlag : undefined
        )

        expect(adventCalendarAccess(liveFlags, receivedFeatureFlags)).toBe(expected)
    })
})
