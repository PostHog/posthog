import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import type { TransactionalEmailImpactSessionsApi } from 'products/messaging/frontend/generated/api.schemas'
import type {
    ObservationRequestApi,
    ObservationRequestSessionApi,
} from 'products/replay_vision/frontend/generated/api.schemas'

import { SCAN_POLL_INTERVAL_MS, afterClickingScanLogic } from './afterClickingScanLogic'

const WORKFLOW_ID = '0192c3a4-5b6c-7d8e-9f01-23456789abcd'
const REQUEST_ID = '01a21d51-012a-7d3d-a576-b38b7254d78a'
const NO_SKIPS = { busy: 0, quota: 0 }

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

function scanRequest(status: 'running' | 'completed', sessions: ObservationRequestSessionApi[]): ObservationRequestApi {
    return {
        id: REQUEST_ID,
        status,
        scanner_id: 'scanner-1',
        reference: `workflows-email:${WORKFLOW_ID}`,
        created_at: '2026-11-27T10:00:00Z',
        sessions,
    }
}

const SUCCEEDED = { state: 'succeeded', observation_id: '01a21d52-3c4d-7e5f-8a9b-0c1d2e3f4a5b' } as const

describe('afterClickingScanLogic', () => {
    let logic: ReturnType<typeof afterClickingScanLogic.build>
    let sessionsAnswer: [number, unknown]
    let sessionsParams: URLSearchParams[]
    let createAnswer: [number, unknown]
    let createBodies: Record<string, unknown>[]
    let createGate: Promise<void>
    let retrieveAnswers: [number, unknown][]
    let retrievedPaths: string[]

    beforeEach(() => {
        sessionsAnswer = [200, SESSIONS]
        sessionsParams = []
        createAnswer = [202, scanRequest('running', [scanSession('session-a'), scanSession('session-b')])]
        createBodies = []
        createGate = Promise.resolve()
        retrieveAnswers = []
        retrievedPaths = []
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact/': () => [404, {}],
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
                    createBodies.push((await request.json()) as Record<string, unknown>)
                    const answer = createAnswer
                    await createGate
                    return answer
                },
            },
        })
        initKeaTests()
        setScannerAccess(AccessControlLevel.Editor)
        silenceKeaLoadersErrors()
        logic = afterClickingScanLogic({ workflowId: WORKFLOW_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
        jest.useRealTimers()
    })

    test.each([
        { questionKey: 'stuck', question: 'Where do people get stuck after clicking?', source: 'suggested' },
        { questionKey: null, question: 'Do people find the pricing page?', source: 'custom' },
    ])(
        'scans the listed sessions with a $source question and follows the scan until it finishes',
        async ({ questionKey, question, source }) => {
            const capture = jest.spyOn(posthog, 'capture')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.scanState).toEqual({ kind: 'questions', sessionCount: 2, hasMore: false })

            retrieveAnswers = [
                [200, scanRequest('running', [scanSession('session-a', SUCCEEDED), scanSession('session-b')])],
                [503, { detail: 'Service unavailable' }],
                [
                    200,
                    scanRequest('completed', [
                        scanSession('session-a', SUCCEEDED),
                        scanSession('session-b', { state: 'failed', scan_outcome: 'failed' }),
                    ]),
                ],
            ]
            jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] })
            logic.actions.askQuestion(question, questionKey)
            await expectLogic(logic).toFinishAllListeners()

            expect(createBodies).toEqual([
                {
                    session_ids: ['session-a', 'session-b'],
                    inline: {
                        prompt: `At some point in this session the person clicked a link in an email and landed on a page whose URL has a ph_workflow_run parameter. Look only at what they did from that page on, and answer this question: ${question}`,
                    },
                    reference: `workflows-email:${WORKFLOW_ID}`,
                    idempotency_key: expect.any(String),
                },
            ])
            expect(logic.values.scanState).toEqual({ kind: 'scanning', done: 0, total: 2, skipped: NO_SKIPS })

            await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS)
            expect(logic.values.scanState).toEqual({ kind: 'scanning', done: 1, total: 2, skipped: NO_SKIPS })

            // A poll the server answers with a 503 keeps the scan going.
            await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS)
            expect(logic.values.scanState).toEqual({ kind: 'scanning', done: 1, total: 2, skipped: NO_SKIPS })

            await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS)
            expect(logic.values.scanState).toEqual({ kind: 'finished', withResult: 1, scanned: 2, skipped: NO_SKIPS })

            // The plugin restarts registered timers when the tab comes back; a finished scan polls no more.
            setTabHidden(true)
            setTabHidden(false)
            await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS * 3)
            expect(retrievedPaths).toEqual(
                Array(3).fill(`/api/projects/${MOCK_TEAM_ID}/vision/requests/${REQUEST_ID}/`)
            )
            expect(capture).toHaveBeenCalledWith(
                'transactional email impact question asked',
                expect.objectContaining({ source, question_key: questionKey })
            )
            expect(
                capture.mock.calls.filter(([event]) => event === 'transactional email impact scan finished')
            ).toEqual([
                [
                    'transactional email impact scan finished',
                    { sessions: 2, sessions_with_result: 1, sessions_skipped: 0, credits_used_up: false },
                ],
            ])
        }
    )

    test.each([
        {
            name: 'AI analysis is not allowed',
            answer: [400, { type: 'validation_error', code: 'ai_data_processing_not_approved', detail: 'off' }],
            state: { kind: 'ai-analysis-not-allowed' },
        },
        {
            name: 'the credits are used up',
            answer: [
                202,
                scanRequest('completed', [
                    scanSession('session-a', { state: 'skipped', scan_outcome: 'skipped_quota' }),
                    scanSession('session-b', { state: 'skipped', scan_outcome: 'skipped_quota' }),
                ]),
            ],
            state: { kind: 'credits-used-up' },
        },
        {
            name: 'some sessions are skipped',
            answer: [
                202,
                scanRequest('completed', [
                    scanSession('session-a', SUCCEEDED),
                    scanSession('session-b', { state: 'skipped', scan_outcome: 'skipped_scanner_limit' }),
                ]),
            ],
            state: { kind: 'finished', withResult: 1, scanned: 1, skipped: { busy: 1, quota: 0 } },
        },
        {
            name: 'the server fails',
            answer: [500, { detail: 'Server error' }],
            state: { kind: 'scan-error', message: "Replay vision couldn't scan these sessions. Try again." },
        },
    ] as { name: string; answer: [number, unknown]; state: unknown }[])(
        'says so when $name',
        async ({ answer, state }) => {
            await expectLogic(logic).toFinishAllListeners()
            createAnswer = answer

            await expectLogic(logic, () =>
                logic.actions.askQuestion('Where do people get stuck after clicking?', 'stuck')
            )
                .toFinishAllListeners()
                .toMatchValues({ scanState: state })
        }
    )

    it('starts the scan again with the same idempotency key on retry', async () => {
        await expectLogic(logic).toFinishAllListeners()
        createAnswer = [500, {}]
        await expectLogic(logic, () => logic.actions.askQuestion('Where do people get stuck after clicking?', 'stuck'))
            .toFinishAllListeners()
            .toMatchValues({ scanState: expect.objectContaining({ kind: 'scan-error' }) })

        createAnswer = [202, scanRequest('completed', [scanSession('session-a', SUCCEEDED)])]
        await expectLogic(logic, () => logic.actions.retryScan())
            .toFinishAllListeners()
            .toMatchValues({ scanState: { kind: 'finished', withResult: 1, scanned: 1, skipped: NO_SKIPS } })

        expect(createBodies).toHaveLength(2)
        expect(createBodies[1].idempotency_key).toEqual(createBodies[0].idempotency_key)
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

    it('lists the sessions of a new period and drops the scan of the old one', async () => {
        await expectLogic(logic).toFinishAllListeners()
        createAnswer = [202, scanRequest('completed', [scanSession('session-a', SUCCEEDED)])]
        await expectLogic(logic, () => logic.actions.askQuestion('Where do people get stuck after clicking?', 'stuck'))
            .toFinishAllListeners()
            .toMatchValues({ scanState: expect.objectContaining({ kind: 'finished' }) })

        await expectLogic(logic, () => logic.actions.setDays(1))
            .toFinishAllListeners()
            .toMatchValues({ scanState: { kind: 'questions', sessionCount: 2, hasMore: false } })

        expect(sessionsParams).toHaveLength(2)
        expect(sessionsParams[1].get('workflow_id')).toBe(WORKFLOW_ID)
        expect(Math.round(dayjs().diff(dayjs(sessionsParams[1].get('date_from')), 'hour', true))).toBe(24)
    })
    it('keeps the new period when a scan of the old one fails late', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let failOldScan: () => void = () => {}
        createGate = new Promise((resolve) => (failOldScan = resolve))
        createAnswer = [500, {}]
        const capture = jest.spyOn(posthog, 'capture')
        logic.actions.askQuestion('Where do people get stuck after clicking?', 'stuck')

        await expectLogic(logic, () => logic.actions.setDays(1)).toDispatchActions(['loadSessionsSuccess'])
        failOldScan()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ scanState: { kind: 'questions', sessionCount: 2, hasMore: false } })

        expect(capture).not.toHaveBeenCalledWith('transactional email impact scan failed', expect.anything())
    })

    test.each([
        {
            name: 'outside the main environment',
            team: { ...MOCK_DEFAULT_TEAM, id: MOCK_TEAM_ID + 1 },
            access: AccessControlLevel.Editor,
            sensitive: false,
            state: { kind: 'not-main-environment' },
        },
        {
            name: 'to a viewer of scanners',
            team: MOCK_DEFAULT_TEAM,
            access: AccessControlLevel.Viewer,
            sensitive: false,
            state: { kind: 'no-access', reason: expect.stringContaining('(viewer)') },
        },
        {
            name: 'while link tracking is off',
            team: {
                ...MOCK_DEFAULT_TEAM,
                workflows_config: { ...MOCK_DEFAULT_TEAM.workflows_config, email_workflow_run_link_tag_enabled: false },
            },
            access: AccessControlLevel.Editor,
            sensitive: false,
            state: { kind: 'link-tagging-off' },
        },
        {
            name: 'for an always sensitive email',
            team: MOCK_DEFAULT_TEAM,
            access: AccessControlLevel.Editor,
            sensitive: true,
            state: { kind: 'sensitive-email' },
        },
    ])('offers no questions $name', async ({ team, access, sensitive, state }) => {
        logic.unmount()
        setScannerAccess(access)
        teamLogic.actions.loadCurrentTeamSuccess(team as typeof MOCK_DEFAULT_TEAM)
        logic = afterClickingScanLogic({ workflowId: WORKFLOW_ID, alwaysSensitive: sensitive })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ scanState: state })
    })
})
