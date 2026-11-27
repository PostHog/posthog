import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import type { TransactionalEmailImpactSessionsApi } from 'products/messaging/frontend/generated/api.schemas'
import type {
    ObservationRequestApi,
    ObservationRequestSessionApi,
} from 'products/replay_vision/frontend/generated/api.schemas'

import { SCAN_POLL_INTERVAL_MS, afterClickingScanLogic, scanBlockedState } from './afterClickingScanLogic'
import type { LinkTagging } from './impactSteps'

const WORKFLOW_ID = '0192c3a4-5b6c-7d8e-9f01-23456789abcd'
const REQUEST_ID = '01a21d51-012a-7d3d-a576-b38b7254d78a'

function pollPath(requestId: string): string {
    return `/api/projects/${MOCK_TEAM_ID}/vision/requests/${requestId}/`
}

function setScannerAccess(level: AccessControlLevel): void {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        resource_access_control: {
            ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
            [AccessControlResourceType.ReplayScanner]: level,
            [AccessControlResourceType.SessionRecording]: AccessControlLevel.Viewer,
        },
    } as AppContext
}

// The disposables plugin pauses and resumes on `visibilitychange`, reading `document.hidden`.
function setTabHidden(hidden: boolean): void {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    document.dispatchEvent(new Event('visibilitychange'))
}

const SESSIONS: TransactionalEmailImpactSessionsApi = {
    sessions: [
        { session_id: 'session-a', message_id: 'message-a', first_pageview_at: '2026-11-26T10:00:00Z' },
        { session_id: 'session-b', message_id: 'message-b', first_pageview_at: '2026-11-26T09:00:00Z' },
    ],
    has_more: false,
}

function scanSession(
    session_id: string,
    overrides: Partial<ObservationRequestSessionApi> = {}
): ObservationRequestSessionApi {
    return {
        session_id,
        scan_outcome: 'started',
        state: 'running',
        observation_id: null,
        scanner_result: null,
        ...overrides,
    }
}

function scanRequest(
    status: 'running' | 'completed',
    sessions: ObservationRequestSessionApi[],
    id: string = REQUEST_ID
): ObservationRequestApi {
    return {
        id,
        status,
        scanner_id: 'scanner-1',
        reference: `workflows-email:${WORKFLOW_ID}`,
        created_at: '2026-11-27T10:00:00Z',
        sessions,
    }
}

const SUCCEEDED: Partial<ObservationRequestSessionApi> = {
    state: 'succeeded',
    observation_id: '01a21d52-3c4d-7e5f-8a9b-0c1d2e3f4a5b',
    scanner_result: {
        model_output: { scanner_type: 'monitor', verdict: 'no', reasoning: 'They left the pricing page.' },
        signals_count: 0,
    },
}
const GENERIC_ERROR = "Replay vision couldn't scan these sessions. Try again."

describe('afterClickingScanLogic', () => {
    let logic: ReturnType<typeof afterClickingScanLogic.build>
    let sessionsAnswer: [number, unknown]
    let sessionsParams: URLSearchParams[]
    let createAnswer: [number, unknown]
    let createBodies: Record<string, unknown>[]
    let createGate: Promise<void>
    let retrieveAnswers: [number, unknown][]
    let retrievedPaths: string[]
    let capturedEvents: { event: string; properties: unknown }[]

    beforeEach(() => {
        capturedEvents = []
        jest.spyOn(posthog, 'capture').mockImplementation((event, properties) => {
            capturedEvents.push({ event, properties })
            return undefined
        })
        sessionsAnswer = [200, SESSIONS]
        sessionsParams = []
        createAnswer = [202, scanRequest('running', [scanSession('session-a'), scanSession('session-b')])]
        createBodies = []
        createGate = Promise.resolve()
        retrieveAnswers = []
        retrievedPaths = []
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact_sessions/': ({ request }) => {
                    sessionsParams.push(new URL(request.url).searchParams)
                    return sessionsAnswer
                },
                '/api/projects/:team_id/vision/requests/:id/': ({ request }) => {
                    retrievedPaths.push(new URL(request.url).pathname)
                    return retrieveAnswers.shift() ?? [500, {}]
                },
            },
            post: {
                '/api/projects/:team_id/vision/requests/': async ({ request }) => {
                    const answer = createAnswer
                    createBodies.push((await request.json()) as Record<string, unknown>)
                    await createGate
                    return answer
                },
            },
        })
        initKeaTests()
        setScannerAccess(AccessControlLevel.Editor)
        silenceKeaLoadersErrors()
        logic = afterClickingScanLogic({ workflowId: WORKFLOW_ID, days: 7 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
        jest.useRealTimers()
    })

    it("scans the period's sessions with the fixed question and lists each session's answer", async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.scanState).toEqual({ kind: 'ready', sessionCount: 2, hasMore: false })
        expect(sessionsParams[0].get('workflow_id')).toBe(WORKFLOW_ID)
        expect(Math.round(dayjs().diff(dayjs(sessionsParams[0].get('date_from')), 'hour', true))).toBe(7 * 24)

        retrieveAnswers = [
            [200, scanRequest('running', [scanSession('session-a', SUCCEEDED), scanSession('session-b')])],
            [
                200,
                scanRequest('completed', [
                    scanSession('session-a', SUCCEEDED),
                    scanSession('session-b', { state: 'failed' }),
                ]),
            ],
        ]
        jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] })
        logic.actions.startScan()
        await expectLogic(logic).toFinishAllListeners()

        expect(createBodies).toEqual([
            {
                session_ids: ['session-a', 'session-b'],
                inline: {
                    prompt: 'At some point in this session the person clicked a link in an email and landed on a page whose URL has a ph_workflow_run parameter. Look only at what they did from that page on, and answer this question: Did the person finish what they came to do?',
                },
                reference: `workflows-email:${WORKFLOW_ID}`,
                idempotency_key: expect.any(String),
            },
        ])
        expect(logic.values.scanState).toEqual({ kind: 'scanning', done: 0, total: 2 })

        await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS)
        expect(logic.values.scanState).toEqual({ kind: 'scanning', done: 1, total: 2 })

        await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS)
        expect(logic.values.scanState).toEqual({
            kind: 'finished',
            answers: [{ sessionId: 'session-a', verdict: 'no', reasoning: 'They left the pricing page.' }],
            withoutAnswer: 1,
        })

        // The plugin restarts registered timers when the tab comes back; a finished scan polls no more.
        setTabHidden(true)
        setTabHidden(false)
        await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS * 3)
        expect(retrievedPaths).toEqual(Array(2).fill(pollPath(REQUEST_ID)))
        expect(capturedEvents).toEqual([
            { event: 'transactional email impact scan started', properties: { sessions: 2, days: 7 } },
        ])
    })

    test.each([
        { name: 'a limit skipped it', session: { state: 'skipped', scan_outcome: 'skipped_limit' } },
        {
            name: 'its result has no verdict',
            session: { ...SUCCEEDED, scanner_result: { model_output: {}, signals_count: 0 } },
        },
    ] as { name: string; session: Partial<ObservationRequestSessionApi> }[])(
        'counts a session without an answer when $name',
        async ({ session }) => {
            await expectLogic(logic).toFinishAllListeners()
            createAnswer = [
                202,
                scanRequest('completed', [scanSession('session-a', SUCCEEDED), scanSession('session-b', session)]),
            ]

            await expectLogic(logic, () => logic.actions.startScan())
                .toFinishAllListeners()
                .toMatchValues({
                    scanState: {
                        kind: 'finished',
                        answers: [expect.objectContaining({ sessionId: 'session-a' })],
                        withoutAnswer: 1,
                    },
                })
        }
    )

    test.each([
        {
            name: "the API's reason when it refuses the scan",
            answer: [400, { type: 'validation_error', code: 'ai_data_processing_not_approved', detail: 'AI is off.' }],
            message: 'AI is off.',
        },
        {
            name: 'a general error when the server fails',
            answer: [500, { detail: 'Server error' }],
            message: GENERIC_ERROR,
        },
    ] as { name: string; answer: [number, unknown]; message: string }[])('shows $name', async ({ answer, message }) => {
        await expectLogic(logic).toFinishAllListeners()
        createAnswer = answer

        await expectLogic(logic, () => logic.actions.startScan())
            .toFinishAllListeners()
            .toMatchValues({ scanState: { kind: 'scan-error', message } })
    })

    it('stops polling once a poll fails, and starts a new scan on Scan again', async () => {
        await expectLogic(logic).toFinishAllListeners()
        createAnswer = [202, scanRequest('running', [scanSession('session-a', SUCCEEDED), scanSession('session-b')])]
        retrieveAnswers = [[503, { detail: 'Service unavailable' }]]
        jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] })
        logic.actions.startScan()
        await expectLogic(logic).toFinishAllListeners()

        await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS)
        expect(logic.values.scanState).toEqual({ kind: 'scan-error', message: GENERIC_ERROR })
        setTabHidden(true)
        setTabHidden(false)
        await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS * 3)
        expect(retrievedPaths).toHaveLength(1)

        let answerNewScan: () => void = () => {}
        createGate = new Promise((resolve) => (answerNewScan = resolve))
        logic.actions.startScan()
        // The failed scan's last state belongs to the old request, so the new one starts from zero.
        expect(logic.values.scanState).toEqual({ kind: 'scanning', done: 0, total: 2 })
        answerNewScan()
        await expectLogic(logic).toFinishAllListeners()
        expect(createBodies).toHaveLength(2)
        expect(createBodies[1].idempotency_key).not.toEqual(createBodies[0].idempotency_key)
    })

    test.each([
        { name: 'no sessions', answer: [200, { sessions: [], has_more: false }], state: { kind: 'no-sessions' } },
        { name: 'a failed session list', answer: [500, {}], state: { kind: 'sessions-error' } },
    ] as { name: string; answer: [number, unknown]; state: unknown }[])(
        'shows $name apart from loading',
        async ({ answer, state }) => {
            logic.unmount()
            sessionsAnswer = answer
            logic.mount()
            expect(logic.values.scanState).toEqual({ kind: 'loading-sessions' })

            await expectLogic(logic).toFinishAllListeners().toMatchValues({ scanState: state })
        }
    )

    test.each([
        {
            name: 'outside the main environment',
            team: { ...MOCK_DEFAULT_TEAM, id: MOCK_TEAM_ID + 1 },
            access: AccessControlLevel.Editor,
            linkTagging: 'on',
            state: { kind: 'not-main-environment' },
        },
        {
            name: 'to a viewer of scanners',
            team: MOCK_DEFAULT_TEAM,
            access: AccessControlLevel.Viewer,
            linkTagging: 'on',
            state: { kind: 'no-access', reason: expect.stringContaining('(viewer)') },
        },
        {
            name: 'while link tracking is off',
            team: MOCK_DEFAULT_TEAM,
            access: AccessControlLevel.Editor,
            linkTagging: 'off',
            state: { kind: 'link-tagging-off' },
        },
        {
            name: 'for an always sensitive email',
            team: MOCK_DEFAULT_TEAM,
            access: AccessControlLevel.Editor,
            linkTagging: 'sensitive-email',
            state: { kind: 'sensitive-email' },
        },
        {
            name: 'never for an editor in the main environment',
            team: MOCK_DEFAULT_TEAM,
            access: AccessControlLevel.Editor,
            linkTagging: 'on',
            state: null,
        },
    ] as {
        name: string
        team: typeof MOCK_DEFAULT_TEAM
        access: AccessControlLevel
        linkTagging: LinkTagging
        state: unknown
    }[])('blocks the scan $name', ({ team, access, linkTagging, state }) => {
        setScannerAccess(access)
        expect(scanBlockedState(team, linkTagging)).toEqual(state)
    })
})
