import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'

import { initKeaTests } from '~/test/init'

import { adventCalendarAccessLogic } from './adventCalendarAccessLogic'

const FLAG = FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR

type FlagsCallback = (flags: string[], variants: Record<string, string | boolean>, context?: object) => void

type Load = { outcome: 'failed' | 'succeeded' | 'no outcome'; enabledFlags: Record<string, boolean> }

type Visit = {
    pageFlags: Record<string, boolean | string> | null | 'no page object'
    failedBeforeMount?: unknown
    loads: Load[]
}

const failed = (enabledFlags: Record<string, boolean> = {}): Load => ({ outcome: 'failed', enabledFlags })
const succeeded = (enabledFlags: Record<string, boolean> = {}): Load => ({ outcome: 'succeeded', enabledFlags })
const noOutcome = (enabledFlags: Record<string, boolean> = {}): Load => ({ outcome: 'no outcome', enabledFlags })

describe('adventCalendarAccessLogic', () => {
    let flagCallbacks: FlagsCallback[]

    beforeEach(() => {
        localStorage.clear()
        flagCallbacks = []
        jest.mocked(posthog.onFeatureFlags).mockImplementation((callback) => {
            flagCallbacks.push(callback as FlagsCallback)
            return () => {}
        })
    })

    afterEach(() => {
        delete window.POSTHOG_GLOBAL_ERRORS
        delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        jest.mocked(posthog.get_property).mockReset()
    })

    it.each<[string, Visit, boolean | undefined]>([
        [
            'a successful load shows the flag on',
            { pageFlags: { [FLAG]: false }, loads: [succeeded({ [FLAG]: true })] },
            true,
        ],
        [
            'a successful load with the flag off wins over a page decision on',
            { pageFlags: { [FLAG]: true }, loads: [succeeded()] },
            false,
        ],
        ['a failed load shows the page decision on', { pageFlags: { [FLAG]: true }, loads: [failed()] }, true],
        [
            'a failed load shows the page decision off over a stored flag on',
            { pageFlags: { [FLAG]: false }, loads: [failed({ [FLAG]: true })] },
            false,
        ],
        [
            'a successful retry shows the flag off even when no enabled flag changed',
            { pageFlags: { [FLAG]: true }, loads: [failed({ 'other-flag': true }), succeeded({ 'other-flag': true })] },
            false,
        ],
        [
            'a flag sync from another tab keeps the page decision',
            { pageFlags: { [FLAG]: true }, loads: [failed(), noOutcome()] },
            true,
        ],
        ['nothing known yet is unknown', { pageFlags: { [FLAG]: true }, loads: [] }, undefined],
        [
            'a load that failed before mount shows the page decision',
            { pageFlags: { [FLAG]: true }, failedBeforeMount: ['connection_error'], loads: [noOutcome()] },
            true,
        ],
        [
            'a load that succeeded after an earlier failure before mount shows the flag',
            { pageFlags: { [FLAG]: true }, failedBeforeMount: [], loads: [noOutcome()] },
            false,
        ],
        [
            'an error record from before mount that is not a list keeps the flag',
            { pageFlags: { [FLAG]: true }, failedBeforeMount: 'connection_error', loads: [noOutcome()] },
            false,
        ],
        [
            'a failed load on a page without the identity object keeps the stored flag',
            { pageFlags: 'no page object', loads: [failed({ [FLAG]: true })] },
            true,
        ],
        [
            'a failed load on a page without flag decisions keeps the stored flag',
            { pageFlags: null, loads: [failed({ [FLAG]: true })] },
            true,
        ],
        [
            'a failed load on a page that left the flag out keeps the stored flag',
            { pageFlags: { 'other-flag': true }, loads: [failed()] },
            false,
        ],
        [
            'a failed load ignores a page value that is not a boolean',
            { pageFlags: { [FLAG]: 'true' }, loads: [failed()] },
            false,
        ],
    ])('%s', (_name, { pageFlags, failedBeforeMount, loads }, expected) => {
        if (pageFlags !== 'no page object') {
            window.POSTHOG_USER_IDENTITY_WITH_FLAGS = { distinctID: 'person-1', featureFlags: pageFlags }
        }
        if (failedBeforeMount !== undefined) {
            window.POSTHOG_GLOBAL_ERRORS = { onFeatureFlagsLoadError: true }
            jest.mocked(posthog.get_property).mockImplementation((key) =>
                key === '$feature_flag_errors' ? failedBeforeMount : undefined
            )
        }
        initKeaTests()
        const logic = adventCalendarAccessLogic()
        logic.mount()

        for (const { outcome, enabledFlags } of loads) {
            for (const callback of flagCallbacks) {
                if (outcome === 'no outcome') {
                    callback(Object.keys(enabledFlags), enabledFlags)
                } else {
                    callback(Object.keys(enabledFlags), enabledFlags, { errorsLoading: outcome === 'failed' })
                }
            }
        }

        expect(logic.values.calendarOn).toBe(expected)
    })
})
