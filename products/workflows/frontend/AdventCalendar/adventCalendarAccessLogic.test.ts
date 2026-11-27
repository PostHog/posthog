import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'

import { initKeaTests } from '~/test/init'
import type { AppContext } from '~/types'

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

type View = 'waiting' | 'calendar' | 'not found'

type DecisionRow = {
    page: 'on' | 'off' | 'absent'
    persisted: 'persisted' | 'not persisted'
    cached: 'first visit' | 'stored without it' | 'stored on' | 'stored off'
    load:
        | 'not yet'
        | 'blocked'
        | 'answers on'
        | 'answers off'
        | 'calendar flag failed'
        | 'unrelated error, answers on'
        | 'unrelated error, answers off'
    timeout: 'before timeout' | 'after timeout' | 'flags arrived'
    sees: View
}

type DecisionTableRow = [
    DecisionRow['page'],
    DecisionRow['persisted'],
    DecisionRow['cached'],
    DecisionRow['load'],
    DecisionRow['timeout'],
    DecisionRow['sees'],
]

const DECISION_TABLE: DecisionTableRow[] = [
    ['on', 'not persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['on', 'not persisted', 'first visit', 'not yet', 'after timeout', 'not found'],
    ['on', 'not persisted', 'first visit', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'first visit', 'answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'first visit', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'first visit', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['on', 'not persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['on', 'not persisted', 'stored without it', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored without it', 'answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored without it', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored without it', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['on', 'not persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['on', 'not persisted', 'stored on', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored on', 'answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored on', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored on', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['on', 'not persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['on', 'not persisted', 'stored off', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored off', 'answers off', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored off', 'calendar flag failed', 'flags arrived', 'not found'],
    ['on', 'not persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'not persisted', 'stored off', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['on', 'persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['on', 'persisted', 'first visit', 'not yet', 'after timeout', 'calendar'],
    ['on', 'persisted', 'first visit', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'first visit', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['on', 'persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['on', 'persisted', 'stored without it', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored without it', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['on', 'persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['on', 'persisted', 'stored on', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored on', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['on', 'persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['on', 'persisted', 'stored off', 'blocked', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored off', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['on', 'persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['off', 'not persisted', 'first visit', 'not yet', 'after timeout', 'not found'],
    ['off', 'not persisted', 'first visit', 'blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'first visit', 'answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'first visit', 'calendar flag failed', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'first visit', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['off', 'not persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['off', 'not persisted', 'stored without it', 'blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored without it', 'answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored without it', 'calendar flag failed', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored without it', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['off', 'not persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['off', 'not persisted', 'stored on', 'blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored on', 'answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored on', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored on', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['off', 'not persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['off', 'not persisted', 'stored off', 'blocked', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored off', 'answers off', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored off', 'calendar flag failed', 'flags arrived', 'not found'],
    ['off', 'not persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['off', 'not persisted', 'stored off', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'not persisted', 'first visit', 'not yet', 'after timeout', 'not found'],
    ['absent', 'not persisted', 'first visit', 'blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'first visit', 'answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'first visit', 'calendar flag failed', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'first visit', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'not persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored without it', 'answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'calendar flag failed', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored without it', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'not persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored on', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored on', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'not persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['absent', 'not persisted', 'stored off', 'blocked', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored off', 'answers off', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored off', 'calendar flag failed', 'flags arrived', 'not found'],
    ['absent', 'not persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'not persisted', 'stored off', 'unrelated error, answers off', 'flags arrived', 'not found'],
    ['absent', 'persisted', 'first visit', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'persisted', 'first visit', 'not yet', 'after timeout', 'calendar'],
    ['absent', 'persisted', 'first visit', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'first visit', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'first visit', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'first visit', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored without it', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'persisted', 'stored without it', 'not yet', 'after timeout', 'not found'],
    ['absent', 'persisted', 'stored without it', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored without it', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored without it', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored without it', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored on', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'persisted', 'stored on', 'not yet', 'after timeout', 'calendar'],
    ['absent', 'persisted', 'stored on', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored on', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored on', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored on', 'unrelated error, answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored off', 'not yet', 'before timeout', 'waiting'],
    ['absent', 'persisted', 'stored off', 'not yet', 'after timeout', 'not found'],
    ['absent', 'persisted', 'stored off', 'blocked', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored off', 'answers on', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored off', 'calendar flag failed', 'flags arrived', 'calendar'],
    ['absent', 'persisted', 'stored off', 'unrelated error, answers on', 'flags arrived', 'calendar'],
]

function toView(calendarOn: boolean | undefined): View {
    return calendarOn === undefined ? 'waiting' : calendarOn ? 'calendar' : 'not found'
}

function masterView(): View {
    if (!featureFlagLogic.values.receivedFeatureFlags && !appLogic.values.featureFlagsTimedOut) {
        return 'waiting'
    }
    return featureFlagLogic.values.featureFlags[FLAG] ? 'calendar' : 'not found'
}

function sdkValueBeforeLoad({ page, cached }: DecisionRow): 'on' | 'off' | 'none' {
    if (cached === 'first visit') {
        return page === 'absent' ? 'none' : page
    }
    return cached === 'stored on' ? 'on' : cached === 'stored off' ? 'off' : 'none'
}

function setTabHidden(hidden: boolean): void {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('adventCalendarAccessLogic', () => {
    let flagCallbacks: Set<FlagsCallback>
    let loadedFlags: Record<string, boolean> | null

    beforeEach(() => {
        localStorage.clear()
        flagCallbacks = new Set()
        loadedFlags = null
        jest.mocked(posthog.onFeatureFlags).mockImplementation((callback) => {
            flagCallbacks.add(callback as FlagsCallback)
            if (loadedFlags) {
                ;(callback as FlagsCallback)(Object.keys(loadedFlags), loadedFlags)
            }
            return () => flagCallbacks.delete(callback as FlagsCallback)
        })
    })

    afterEach(() => {
        setTabHidden(false)
        delete window.POSTHOG_GLOBAL_ERRORS
        delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        delete window.POSTHOG_APP_CONTEXT
        jest.mocked(posthog.get_property).mockReset()
    })

    function openCalendar(
        row: DecisionRow,
        opened: 'before the load' | 'after the load'
    ): { sees: View; master: View } {
        localStorage.clear()
        flagCallbacks.clear()
        loadedFlags = null
        delete window.POSTHOG_GLOBAL_ERRORS
        jest.mocked(posthog.get_property).mockReset()
        window.POSTHOG_APP_CONTEXT = {
            persisted_feature_flags: row.persisted === 'persisted' ? [FLAG] : [],
        } as unknown as AppContext
        if (row.page === 'absent') {
            delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        } else {
            window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
                distinctID: 'person-1',
                featureFlags: { [FLAG]: row.page === 'on' },
            }
        }
        const storedOn = row.cached === 'stored on' || (row.cached === 'first visit' && row.persisted === 'persisted')
        if (row.cached !== 'first visit' || storedOn) {
            localStorage.setItem(
                'lib.logic.featureFlagLogic.featureFlags',
                JSON.stringify(storedOn ? { [FLAG]: true } : {})
            )
        }
        initKeaTests()
        featureFlagLogic.mount()
        appLogic.mount()
        const logic = adventCalendarAccessLogic()

        const blocked = row.load === 'blocked'
        const before = sdkValueBeforeLoad(row)
        const after =
            blocked || row.load === 'calendar flag failed' ? before : row.load.endsWith('answers on') ? 'on' : 'off'
        const errors = blocked
            ? ['connection_error']
            : row.load === 'calendar flag failed' || row.load.startsWith('unrelated error')
              ? ['errors_while_computing_flags']
              : []
        const details = row.load === 'calendar flag failed' && before === 'none' ? { [FLAG]: { failed: true } } : {}
        const loadFlags = (): void => {
            if (blocked) {
                window.POSTHOG_GLOBAL_ERRORS = { onFeatureFlagsLoadError: true }
            }
            jest.mocked(posthog.get_property).mockImplementation((key) =>
                key === '$feature_flag_errors' ? errors : key === '$feature_flag_details' ? details : undefined
            )
            const enabled: Record<string, boolean> = after === 'on' ? { [FLAG]: true } : {}
            loadedFlags = enabled
            for (const callback of flagCallbacks) {
                callback(Object.keys(enabled), enabled, { errorsLoading: blocked })
            }
        }

        if (row.load === 'not yet') {
            logic.mount()
            if (row.timeout === 'after timeout') {
                appLogic.actions.ignoreFeatureFlags()
            }
        } else if (opened === 'after the load') {
            loadFlags()
            logic.mount()
        } else {
            logic.mount()
            loadFlags()
        }

        const result = { sees: toView(logic.values.calendarOn), master: masterView() }
        logic.unmount()
        appLogic.unmount()
        return result
    }

    describe('decision table: a persisted flag never decides off because it is rolled out to everyone, and the timeout stops mattering once flags arrive', () => {
        it.each(DECISION_TABLE)(
            'page %s, %s, %s, flags %s, %s: sees %s',
            (page, persisted, cached, load, timeout, expected) => {
                const row: DecisionRow = { page, persisted, cached, load, timeout, sees: expected }
                const undecided = load === 'blocked' || load === 'calendar flag failed'
                const pageView: View | null = page === 'absent' ? null : page === 'on' ? 'calendar' : 'not found'
                const openings =
                    load === 'not yet'
                        ? (['before the load'] as const)
                        : (['before the load', 'after the load'] as const)
                for (const opened of openings) {
                    const { sees, master } = openCalendar(row, opened)
                    expect({ opened, sees }).toEqual({ opened, sees: expected })
                    expect({
                        opened,
                        sees,
                        master,
                        sameAsMasterOrPageAfterAnUndecidedLoad: sees === master || (undecided && sees === pageView),
                    }).toMatchObject({ sameAsMasterOrPageAfterAnUndecidedLoad: true })
                }
            }
        )
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
