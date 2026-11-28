import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext, TeamType } from '~/types'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'
import type {
    CreateObservationRequestApi,
    ObservationRequestApi,
    RequestSessionStateEnumApi,
} from 'products/replay_vision/frontend/generated/api.schemas'

import { SCAN_POLL_INTERVAL_MS } from './afterClickingScanLogic'
import { EmailImpactTab } from './EmailImpactTab'

const WORKFLOW_ID = '0192c3a4-5b6c-7d8e-9f01-23456789abcd'
const NOW = new Date('2026-11-28T12:00:00Z')
const LANDINGS = [
    { session_id: 'session-recording', first_pageview_at: '2026-11-28T00:00:00Z' },
    { session_id: 'session-a', first_pageview_at: '2026-11-26T10:00:00Z' },
    { session_id: 'session-b', first_pageview_at: '2026-11-26T10:00:00Z' },
]
const REPLAY_ON = { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: true }
const READY = 'Ask Replay vision about these sessions'
const ANSWER = "They opened the invoice page, but the page didn't show whether they found the download."
const OLD_ANSWER = 'They opened the pricing page and left after a minute.'

const IMPACT: TransactionalEmailImpactApi = {
    sent: 10,
    delivered: 9,
    opened: 5,
    clicked: 2,
    not_clicked: 7,
    untracked: 0,
    clicks_untracked: 0,
    window_days: 7,
    sessions: 2,
    sessions_capped_at: null,
    link_tagging_enabled: true,
    after_click: null,
    without_click: null,
}

const REPLAY_OFF_COPY =
    'Replay vision will watch the sessions this email starts and group what people did. It needs session replay to record those sessions.'

interface FakeReplayVision {
    bodies: CreateObservationRequestApi[]
    scansByKey: Map<string, ObservationRequestApi>
    startsRunning: boolean
    endStates: RequestSessionStateEnumApi[] | null
    lostCreateAnswers: number
    failedPolls: number
    pollFailure: [number, Record<string, string>]
    createGate: Promise<void>
    pollGate: Promise<void>
    polls: number
    answers: Map<string, string>
}

function finished(scan: ObservationRequestApi, answer: string): ObservationRequestApi {
    return {
        ...scan,
        status: 'completed',
        sessions: [
            {
                ...scan.sessions[0],
                state: 'succeeded',
                scanner_result: {
                    model_output: { scanner_type: 'monitor', verdict: 'inconclusive', reasoning: answer },
                    signals_count: 0,
                },
            },
            ...scan.sessions.slice(1),
        ],
    }
}

function parseDatetime(value: string): number {
    const day = /^(\d{4})-(\d{2})-(\d{2})T/.exec(value)
    const at = Date.parse(value)
    if (!day || Number.isNaN(at)) {
        return NaN
    }
    const [year, month, date] = day.slice(1).map(Number)
    const calendar = new Date(Date.UTC(year, month - 1, date))
    return calendar.getUTCMonth() === month - 1 && calendar.getUTCDate() === date ? at : NaN
}

function byteOrder(a: string, b: string): number {
    return a < b ? -1 : a > b ? 1 : 0
}

function ended(
    scan: ObservationRequestApi,
    endStates: RequestSessionStateEnumApi[] | null,
    answer: string
): ObservationRequestApi {
    if (!endStates) {
        return finished(scan, answer)
    }
    const done = endStates[0] === 'succeeded' ? finished(scan, answer) : { ...scan, status: 'completed' as const }
    return {
        ...done,
        sessions: done.sessions.map((session, index) =>
            endStates[index] === 'succeeded'
                ? session
                : { ...session, scan_outcome: 'started', state: endStates[index], scanner_result: null }
        ),
    }
}

describe('AfterClickingCard', () => {
    let vision: FakeReplayVision
    let failedSessionLists: number
    let sendCapReached: boolean
    let linkTrackingOn: boolean
    let captured: string[]

    beforeEach(() => {
        jest.useFakeTimers({ now: NOW, advanceTimers: true })
        captured = []
        jest.spyOn(posthog, 'capture').mockImplementation((event) => {
            captured.push(event)
            return undefined
        })
        failedSessionLists = 0
        sendCapReached = false
        linkTrackingOn = true
        vision = {
            bodies: [],
            scansByKey: new Map(),
            startsRunning: false,
            endStates: null,
            lostCreateAnswers: 0,
            failedPolls: 0,
            pollFailure: [502, {}],
            createGate: Promise.resolve(),
            pollGate: Promise.resolve(),
            polls: 0,
            answers: new Map(),
        }
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact/': () => [
                    200,
                    { ...IMPACT, link_tagging_enabled: linkTrackingOn },
                ],
                '/api/projects/:team_id/transactional_email_log/impact_sessions/': ({ request }) => {
                    const query = new URL(request.url).searchParams
                    const bounds: Record<string, number> = {}
                    for (const attr of ['date_from', 'date_to', 'landed_before']) {
                        const value = query.get(attr)
                        bounds[attr] = value === null ? NaN : parseDatetime(value)
                        if (value !== null && Number.isNaN(bounds[attr])) {
                            return [400, { attr, detail: 'Datetime has wrong format.' }]
                        }
                    }
                    if (!linkTrackingOn) {
                        return [200, { sessions: [], has_more: false }]
                    }
                    if (failedSessionLists > 0) {
                        failedSessionLists -= 1
                        return [500, {}]
                    }
                    const from = Number.isNaN(bounds.date_from) ? -Infinity : bounds.date_from
                    const before = Number.isNaN(bounds.landed_before) ? Infinity : bounds.landed_before
                    const landed = LANDINGS.filter(({ first_pageview_at }) => {
                        const at = Date.parse(first_pageview_at)
                        return at >= from && at < before
                    })
                    landed.sort(
                        (a, b) =>
                            Date.parse(b.first_pageview_at) - Date.parse(a.first_pageview_at) ||
                            byteOrder(b.session_id, a.session_id)
                    )
                    const sessions = landed.map((landing) => ({
                        ...landing,
                        message_id: `message-${landing.session_id}`,
                    }))
                    return [
                        200,
                        { sessions: sessions.slice(0, 200), has_more: sessions.length > 200 || sendCapReached },
                    ]
                },
                '/api/projects/:team_id/vision/requests/:id/': async ({ params }) => {
                    vision.polls += 1
                    await vision.pollGate
                    const scan = [...vision.scansByKey.values()].find(({ id }) => id === params.id)
                    if (!scan) {
                        return [404, { detail: 'Not found.' }]
                    }
                    if (vision.failedPolls > 0) {
                        vision.failedPolls -= 1
                        return vision.pollFailure
                    }
                    return [200, finished(scan, vision.answers.get(scan.id) ?? ANSWER)]
                },
            },
            patch: {
                '/api/organizations/:organization_id/projects/:id/': async ({ request }) => {
                    const patch = (await request.json()) as Partial<TeamType>
                    linkTrackingOn = !!patch.workflows_config?.email_workflow_run_link_tag_enabled
                    return [
                        200,
                        {
                            ...REPLAY_ON,
                            workflows_config: { ...REPLAY_ON.workflows_config, ...patch.workflows_config },
                        },
                    ]
                },
            },
            post: {
                '/api/projects/:team_id/vision/requests/': async ({ request }) => {
                    const body = (await request.json()) as CreateObservationRequestApi
                    if (body.session_ids.length === 0) {
                        return [400, { attr: 'session_ids', detail: 'This list may not be empty.' }]
                    }
                    vision.bodies.push(body)
                    await vision.createGate
                    const key = body.idempotency_key ?? `no-key-${vision.bodies.length}`
                    const existing = vision.scansByKey.get(key)
                    const scan: ObservationRequestApi = existing ?? {
                        id: `request-${vision.scansByKey.size + 1}`,
                        status: 'running',
                        scanner_id: 'scanner-1',
                        reference: body.reference ?? '',
                        created_at: '2026-11-27T10:00:00Z',
                        sessions: body.session_ids.map((session_id, index) => ({
                            session_id,
                            scan_outcome: index === 0 ? 'started' : 'skipped_limit',
                            state: index === 0 ? 'running' : 'skipped',
                            observation_id: null,
                            scanner_result: null,
                        })),
                    }
                    vision.scansByKey.set(key, scan)
                    if (vision.lostCreateAnswers > 0) {
                        vision.lostCreateAnswers -= 1
                        return [504, {}]
                    }
                    return [
                        existing ? 200 : 202,
                        vision.startsRunning
                            ? scan
                            : ended(scan, vision.endStates, vision.answers.get(scan.id) ?? ANSWER),
                    ]
                },
            },
        })
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    })

    function setPageHidden(hidden: boolean): void {
        Object.defineProperty(document, 'hidden', { value: hidden, configurable: true })
        document.dispatchEvent(new Event('visibilitychange'))
    }

    function renderTab(
        team: typeof MOCK_DEFAULT_TEAM,
        { replayVision = true, scannerAccess = AccessControlLevel.Editor } = {}
    ): void {
        initKeaTests(true, team)
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.ReplayScanner]: scannerAccess,
                [AccessControlResourceType.SessionRecording]: AccessControlLevel.Viewer,
            },
        } as AppContext
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(
            replayVision ? [FEATURE_FLAGS.WORKFLOWS_EMAIL_IMPACT_REPLAY_VISION] : [],
            { [FEATURE_FLAGS.WORKFLOWS_EMAIL_IMPACT_REPLAY_VISION]: replayVision }
        )
        render(<EmailImpactTab workflowId={WORKFLOW_ID} alwaysSensitive={false} />)
    }

    async function selectPeriod(label: string): Promise<void> {
        await userEvent.click(document.querySelector('[data-attr="email-impact-date-range"]') as HTMLElement)
        await userEvent.click(await screen.findByText(label))
    }

    test.each([
        { replay: false, replayVision: false, shows: REPLAY_OFF_COPY },
        { replay: true, replayVision: false, shows: null },
        { replay: false, replayVision: true, shows: REPLAY_OFF_COPY },
        { replay: true, replayVision: true, shows: READY },
    ])(
        'shows what the card can do with session replay on: $replay and Replay vision on: $replayVision',
        async ({ replay, replayVision, shows }) => {
            renderTab({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: replay }, { replayVision })

            await screen.findByText('Sent')
            if (shows) {
                await screen.findByText(shows)
            }
            expect(screen.queryByText('What people did after clicking') !== null).toBe(shows !== null)
        }
    )

    it("lists the period's sessions again after the list fails to load", async () => {
        failedSessionLists = 1
        renderTab(REPLAY_ON)

        await userEvent.click(await screen.findByText('Try again'))

        expect(await screen.findByText(READY)).toBeInTheDocument()
    })

    it('says it watches some of the sessions when the send cap leaves more out', async () => {
        sendCapReached = true
        renderTab(REPLAY_ON)

        expect(await screen.findByText(/^Replay vision watches 2 of the sessions people started/)).toBeInTheDocument()
    })

    it('shows a failed scan without a retry when every session failed or was lost', async () => {
        vision.endStates = ['failed', 'lost']
        renderTab(REPLAY_ON)

        await userEvent.click(await screen.findByText('Scan sessions'))

        expect(
            await screen.findByText("Replay vision couldn't scan 2 sessions. Reload the page to scan them again.")
        ).toBeInTheDocument()
        expect(screen.queryByText('Try again')).not.toBeInTheDocument()
    })

    it('shows the answers of a scan where some sessions failed', async () => {
        vision.endStates = ['succeeded', 'failed']
        renderTab(REPLAY_ON)

        await userEvent.click(await screen.findByText('Scan sessions'))

        expect(await screen.findByText(ANSWER)).toBeInTheDocument()
        expect(screen.getByText(/^No answer for 1\ssession\.$/)).toBeInTheDocument()
    })

    it("asks the fixed question about the period's sessions and shows each answer", async () => {
        renderTab(REPLAY_ON)

        expect(await screen.findByText(/Sessions from the last day aren't scanned yet/)).toBeInTheDocument()
        await userEvent.click(screen.getByText('Scan sessions'))

        expect(await screen.findByText(ANSWER)).toBeInTheDocument()
        expect(screen.getByText('Inconclusive')).toBeInTheDocument()
        expect(screen.getByText('Watch session').closest('a')).toHaveAttribute(
            'href',
            expect.stringMatching(/\/replay\/session-b$/)
        )
        expect(screen.getByText(/^No answer for 1\ssession\.$/)).toBeInTheDocument()
        expect(vision.bodies).toEqual([
            expect.objectContaining({
                session_ids: ['session-b', 'session-a'],
                inline: {
                    prompt: expect.stringContaining('Did the person finish what they came to do?'),
                    scanner_config: { allow_inconclusive: true },
                },
                reference: `workflows-email:${WORKFLOW_ID}`,
            }),
        ])
        expect(captured).toEqual(
            expect.arrayContaining([
                'transactional email impact scan started',
                'transactional email impact scan completed',
            ])
        )
    })

    test.each([
        { pollFailure: [502, {}] as [number, Record<string, string>], shows: /progress couldn't load/ },
        {
            pollFailure: [403, { detail: 'You no longer have access to these recordings.' }] as [
                number,
                Record<string, string>,
            ],
            shows: /no longer have access/,
        },
    ])('resumes the same scan after a poll fails with $pollFailure.0', async ({ pollFailure, shows }) => {
        jest.useFakeTimers({ now: NOW, doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] })
        vision.startsRunning = true
        vision.failedPolls = 1
        vision.pollFailure = pollFailure
        renderTab(REPLAY_ON)
        const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })

        await user.click(await screen.findByText('Scan sessions'))
        expect(await screen.findByText(/^0 of 1\ssession scanned$/)).toBeInTheDocument()
        await act(() => jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS))
        expect(await screen.findByText(shows)).toBeInTheDocument()
        await user.click(screen.getByText('Try again'))

        expect(await screen.findByText(ANSWER)).toBeInTheDocument()
        expect(vision.bodies).toHaveLength(1)
        expect(captured).toContain('transactional email impact scan failed')
    })

    it('sends one poll when the tab hides and shows while a poll is in flight', async () => {
        jest.useFakeTimers({ now: NOW, doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] })
        vision.startsRunning = true
        let releasePoll = (): void => {}
        vision.pollGate = new Promise((resolve) => {
            releasePoll = resolve
        })
        renderTab(REPLAY_ON)
        const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })

        await user.click(await screen.findByText('Scan sessions'))
        expect(await screen.findByText(/^0 of 1\ssession scanned$/)).toBeInTheDocument()
        await act(() => jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS))
        act(() => setPageHidden(true))
        act(() => setPageHidden(false))
        await act(() => jest.advanceTimersByTimeAsync(SCAN_POLL_INTERVAL_MS))
        releasePoll()

        expect(await screen.findByText(ANSWER)).toBeInTheDocument()
        expect(vision.polls).toBe(1)
    })

    it('finds the scan it started when the answer to its start never arrived', async () => {
        vision.lostCreateAnswers = 1
        renderTab(REPLAY_ON)

        await userEvent.click(await screen.findByText('Scan sessions'))
        await userEvent.click(await screen.findByText('Try again'))

        expect(await screen.findByText(ANSWER)).toBeInTheDocument()
        expect(vision.bodies).toHaveLength(2)
        expect(vision.scansByKey.size).toBe(1)
    })

    it("drops a scan when its period changes, even if the period's scan answers after the switch back", async () => {
        let answerCreate = (): void => {}
        vision.createGate = new Promise((resolve) => {
            answerCreate = resolve
        })
        renderTab(REPLAY_ON)
        await userEvent.click(await screen.findByText('Scan sessions'))
        await screen.findByText('Scanning sessions')

        await selectPeriod('Last 7 days')
        await screen.findByText(READY)
        await selectPeriod('Last 30 days')
        await screen.findByText(READY)
        vision.answers.set('request-1', OLD_ANSWER)
        answerCreate()
        await userEvent.click(screen.getByText('Scan sessions'))

        expect(await screen.findByText(ANSWER)).toBeInTheDocument()
        expect(screen.queryByText(OLD_ANSWER)).not.toBeInTheDocument()
        expect(vision.scansByKey.size).toBe(2)
    })

    it('lists the sessions once link tracking turns on', async () => {
        linkTrackingOn = false
        const trackingOff = { email_workflow_run_link_tag_enabled: false }
        renderTab({ ...REPLAY_ON, workflows_config: { ...REPLAY_ON.workflows_config, ...trackingOff } })
        expect(await screen.findByText('No sessions to scan yet')).toBeInTheDocument()

        await userEvent.click(await screen.findByText('Turn on for project'))

        expect(await screen.findByText(READY)).toBeInTheDocument()
    })

    test.each([
        { case: 'a scanner viewer', team: REPLAY_ON, scannerAccess: AccessControlLevel.Viewer },
        {
            case: 'another environment of the project',
            team: { ...REPLAY_ON, id: 998, project_id: REPLAY_ON.id },
            scannerAccess: AccessControlLevel.Editor,
        },
    ])("doesn't offer a scan to $case", async ({ team, scannerAccess }) => {
        renderTab(team, { scannerAccess })

        expect((await screen.findByText('Scan sessions')).closest('button')).toHaveAttribute('aria-disabled', 'true')
    })
})
