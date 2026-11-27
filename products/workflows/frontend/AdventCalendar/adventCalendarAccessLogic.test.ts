import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'

import { initKeaTests } from '~/test/init'

import { adventCalendarAccessLogic } from './adventCalendarAccessLogic'

const FLAG = FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR

type FlagsCallback = (flags: string[], variants: Record<string, string | boolean>, context?: object) => void

type Step =
    | { outcome: 'failed' | 'succeeded' | 'no outcome'; enabledFlags: Record<string, boolean> }
    | { outcome: 'tab hidden' }

type Visit = {
    pageFlags: Record<string, boolean | string> | null | 'no page object'
    errorsBeforeMount?: unknown
    flagDetails?: unknown
    steps: Step[]
}

const failed = (enabledFlags: Record<string, boolean> = {}): Step => ({ outcome: 'failed', enabledFlags })
const succeeded = (enabledFlags: Record<string, boolean> = {}): Step => ({ outcome: 'succeeded', enabledFlags })
const noOutcome = (enabledFlags: Record<string, boolean> = {}): Step => ({ outcome: 'no outcome', enabledFlags })
const tabHidden: Step = { outcome: 'tab hidden' }

function setTabHidden(hidden: boolean): void {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('adventCalendarAccessLogic', () => {
    let flagCallbacks: Set<FlagsCallback>

    beforeEach(() => {
        localStorage.clear()
        flagCallbacks = new Set()
        jest.mocked(posthog.onFeatureFlags).mockImplementation((callback) => {
            flagCallbacks.add(callback as FlagsCallback)
            return () => flagCallbacks.delete(callback as FlagsCallback)
        })
    })

    afterEach(() => {
        setTabHidden(false)
        delete window.POSTHOG_GLOBAL_ERRORS
        delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        jest.mocked(posthog.get_property).mockReset()
    })

    it.each<[string, Visit, (boolean | undefined)[]]>([
        [
            'a successful load shows the flag on',
            { pageFlags: { [FLAG]: false }, steps: [succeeded({ [FLAG]: true })] },
            [true],
        ],
        [
            'a successful load with the flag off wins over a page decision on',
            { pageFlags: { [FLAG]: true }, steps: [succeeded()] },
            [false],
        ],
        ['a failed load shows the page decision on', { pageFlags: { [FLAG]: true }, steps: [failed()] }, [true]],
        [
            'a failed load shows the page decision off over a stored flag on',
            { pageFlags: { [FLAG]: false }, steps: [failed({ [FLAG]: true })] },
            [false],
        ],
        [
            'a successful retry hides the calendar even when no enabled flag changed',
            { pageFlags: { [FLAG]: true }, steps: [failed({ 'other-flag': true }), succeeded({ 'other-flag': true })] },
            [true, false],
        ],
        [
            'a successful retry while the tab is hidden shows the flag',
            { pageFlags: { [FLAG]: false }, steps: [failed(), tabHidden, succeeded({ [FLAG]: true })] },
            [false, false, true],
        ],
        [
            'a flag sync from another tab keeps the page decision',
            { pageFlags: { [FLAG]: false }, steps: [failed(), noOutcome({ [FLAG]: true })] },
            [false, false],
        ],
        ['nothing known yet is unknown', { pageFlags: { [FLAG]: true }, steps: [] }, [undefined]],
        [
            'a request that failed before mount shows the page decision',
            { pageFlags: { [FLAG]: true }, errorsBeforeMount: ['connection_error'], steps: [noOutcome()] },
            [true],
        ],
        [
            'an error answer before mount shows the page decision',
            { pageFlags: { [FLAG]: true }, errorsBeforeMount: ['api_error_503'], steps: [noOutcome()] },
            [true],
        ],
        [
            'a successful request after an earlier failure before mount shows the flag',
            { pageFlags: { [FLAG]: true }, errorsBeforeMount: [], steps: [noOutcome()] },
            [false],
        ],
        [
            'a successful request with an evaluation error before mount shows the flag',
            {
                pageFlags: { [FLAG]: true },
                errorsBeforeMount: ['errors_while_computing_flags'],
                steps: [noOutcome()],
            },
            [false],
        ],
        [
            'an error record from before mount that is not a list keeps the flag',
            { pageFlags: { [FLAG]: true }, errorsBeforeMount: 'connection_error', steps: [noOutcome()] },
            [false],
        ],
        [
            'a successful retry that failed to evaluate the calendar flag shows the page decision',
            { pageFlags: { [FLAG]: true }, flagDetails: { [FLAG]: { failed: true } }, steps: [failed(), succeeded()] },
            [true, true],
        ],
        [
            'a successful load that failed to evaluate the calendar flag shows the page decision',
            { pageFlags: { [FLAG]: true }, flagDetails: { [FLAG]: { failed: true } }, steps: [succeeded()] },
            [true],
        ],
        [
            'a calendar flag that failed to evaluate before mount shows the page decision',
            { pageFlags: { [FLAG]: true }, flagDetails: { [FLAG]: { failed: true } }, steps: [noOutcome()] },
            [true],
        ],
        [
            'flag details that are not an object keep the flag',
            { pageFlags: { [FLAG]: true }, flagDetails: 'failed', steps: [succeeded()] },
            [false],
        ],
        [
            'flag details without the calendar flag keep the flag',
            { pageFlags: { [FLAG]: true }, flagDetails: { 'other-flag': { failed: true } }, steps: [succeeded()] },
            [false],
        ],
        [
            'a calendar flag detail that is not an object keeps the flag',
            { pageFlags: { [FLAG]: true }, flagDetails: { [FLAG]: null }, steps: [succeeded()] },
            [false],
        ],
        [
            'a failed marker that is not a boolean keeps the flag',
            { pageFlags: { [FLAG]: true }, flagDetails: { [FLAG]: { failed: 'true' } }, steps: [succeeded()] },
            [false],
        ],
        [
            'a failed load on a page without the identity object keeps the stored flag',
            { pageFlags: 'no page object', steps: [failed({ [FLAG]: true })] },
            [true],
        ],
        [
            'a failed load on a page without flag decisions keeps the stored flag',
            { pageFlags: null, steps: [failed({ [FLAG]: true })] },
            [true],
        ],
        [
            'a failed load on a page that left the flag out keeps the stored flag',
            { pageFlags: { 'other-flag': true }, steps: [failed()] },
            [false],
        ],
        [
            'a failed load ignores a page value that is not a boolean',
            { pageFlags: { [FLAG]: 'true' }, steps: [failed()] },
            [false],
        ],
    ])('%s', (_name, { pageFlags, errorsBeforeMount, flagDetails, steps }, expected) => {
        if (pageFlags !== 'no page object') {
            window.POSTHOG_USER_IDENTITY_WITH_FLAGS = { distinctID: 'person-1', featureFlags: pageFlags }
        }
        if (errorsBeforeMount !== undefined) {
            window.POSTHOG_GLOBAL_ERRORS = { onFeatureFlagsLoadError: true }
        }
        jest.mocked(posthog.get_property).mockImplementation((key) =>
            key === '$feature_flag_errors'
                ? errorsBeforeMount
                : key === '$feature_flag_details'
                  ? flagDetails
                  : undefined
        )
        initKeaTests()
        const logic = adventCalendarAccessLogic()
        logic.mount()

        const seen = steps.length ? [] : [logic.values.calendarOn]
        for (const step of steps) {
            if (step.outcome === 'tab hidden') {
                setTabHidden(true)
            } else {
                for (const callback of flagCallbacks) {
                    if (step.outcome === 'no outcome') {
                        callback(Object.keys(step.enabledFlags), step.enabledFlags)
                    } else {
                        callback(Object.keys(step.enabledFlags), step.enabledFlags, {
                            errorsLoading: step.outcome === 'failed',
                        })
                    }
                }
            }
            seen.push(logic.values.calendarOn)
        }

        expect(seen).toEqual(expected)
    })
})
