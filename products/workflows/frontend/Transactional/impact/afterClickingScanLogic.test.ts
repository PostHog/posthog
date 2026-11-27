import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TransactionalEmailImpactSessionsApi } from 'products/messaging/frontend/generated/api.schemas'
import type {
    ObservationRequestApi,
    ObservationRequestSessionApi,
} from 'products/replay_vision/frontend/generated/api.schemas'

import { SCAN_POLL_INTERVAL_MS, afterClickingScanLogic, scanPrompt } from './afterClickingScanLogic'

const WORKFLOW_ID = '0192c3a4-5b6c-7d8e-9f01-23456789abcd'

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
        id: 'request-1',
        status,
        scanner_id: 'scanner-1',
        reference: `workflows-email:${WORKFLOW_ID}`,
        created_at: '2026-11-27T10:00:00Z',
        sessions,
    }
}

const SUCCEEDED = { state: 'succeeded', observation_id: 'observation-1' } as const

describe('afterClickingScanLogic', () => {
    let logic: ReturnType<typeof afterClickingScanLogic.build>
    let sessionsAnswer: [number, unknown]
    let sessionsParams: URLSearchParams[]
    let createAnswer: [number, unknown]
    let createBodies: Record<string, unknown>[]
    let retrieveAnswers: ObservationRequestApi[]
    let retrievedPaths: string[]

    beforeEach(() => {
        sessionsAnswer = [200, SESSIONS]
        sessionsParams = []
        createAnswer = [202, scanRequest('running', [scanSession('session-a'), scanSession('session-b')])]
        createBodies = []
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
                    return [200, retrieveAnswers.shift()]
                },
            },
            post: {
                '/api/projects/:team_id/vision/requests/': async ({ request }) => {
                    createBodies.push((await request.json()) as Record<string, unknown>)
                    return createAnswer
                },
            },
        })
        initKeaTests()
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
                scanRequest('running', [scanSession('session-a', SUCCEEDED), scanSession('session-b')]),
                scanRequest('completed', [
                    scanSession('session-a', SUCCEEDED),
                    scanSession('session-b', { state: 'failed', scan_outcome: 'failed' }),
                ]),
            ]
            jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] })
            logic.actions.askQuestion(question, questionKey)
            await expectLogic(logic).toFinishAllListeners()

            expect(createBodies).toEqual([
                {
                    session_ids: ['session-a', 'session-b'],
                    inline: { prompt: scanPrompt(question) },
                    reference: `workflows-email:${WORKFLOW_ID}`,
                    idempotency_key: expect.any(String),
                },
            ])
            expect(logic.values.scanState).toEqual({ kind: 'scanning', done: 0, total: 2 })

            await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS)
            expect(logic.values.scanState).toEqual({ kind: 'scanning', done: 1, total: 2 })

            await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS)
            expect(logic.values.scanState).toEqual({ kind: 'finished', withResult: 1, total: 2 })

            await jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS * 3)
            expect(retrievedPaths).toEqual([
                `/api/projects/${MOCK_TEAM_ID}/vision/requests/request-1/`,
                `/api/projects/${MOCK_TEAM_ID}/vision/requests/request-1/`,
            ])
            expect(capture).toHaveBeenCalledWith(
                'transactional email impact question asked',
                expect.objectContaining({ source, question_key: questionKey })
            )
            expect(capture).toHaveBeenCalledWith('transactional email impact scan finished', {
                sessions: 2,
                sessions_with_result: 1,
                credits_used_up: false,
            })
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
            .toMatchValues({ scanState: { kind: 'finished', withResult: 1, total: 1 } })

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
})
