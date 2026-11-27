import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils/dom'

import type { TeamPublicType, TeamType } from '~/types'

import { transactionalEmailLogImpactSessionsRetrieve } from 'products/messaging/frontend/generated/api'
import type { TransactionalEmailImpactSessionsApi } from 'products/messaging/frontend/generated/api.schemas'
import { visionRequestsCreate, visionRequestsRetrieve } from 'products/replay_vision/frontend/generated/api'
import type {
    ObservationRequestApi,
    ObservationRequestSessionApi,
} from 'products/replay_vision/frontend/generated/api.schemas'
import { getReplayVisionEditDisabledReason } from 'products/replay_vision/frontend/utils/accessControl'

import { EmailImpactLogicProps, emailImpactLogic } from './emailImpactLogic'
import type { LinkTagging } from './impactSteps'

export const SCAN_POLL_INTERVAL_MS = 3000
export const MAX_POLL_FAILURES = 5
const AI_CONSENT_REQUIRED_CODE = 'ai_data_processing_not_approved'

export interface AfterClickingQuestion {
    key: string
    question: string
}

export const AFTER_CLICKING_QUESTIONS: readonly AfterClickingQuestion[] = [
    { key: 'stuck', question: 'Where do people get stuck after clicking?' },
    { key: 'intent', question: 'What are people trying to do after clicking?' },
    { key: 'frustration', question: 'Where do people get frustrated after clicking?' },
    { key: 'outcome', question: 'Do people finish what they came to do?' },
]

export interface AskedQuestion {
    question: string
    questionKey: string | null
    idempotencyKey: string
}

export type ScanFailure = { kind: 'ai-analysis-not-allowed' } | { kind: 'scan-error'; message: string }

export interface ScanSkips {
    busy: number
    quota: number
    questionLimit: number
    unscannable: number
}

type SessionFate = 'scanned' | keyof ScanSkips

export type ScanBlockedState =
    | { kind: 'not-main-environment' }
    | { kind: 'no-access'; reason: string }
    | { kind: 'link-tagging-off' }
    | { kind: 'sensitive-email' }

export type ScanOutcomeState =
    | { kind: 'finished'; withResult: number; scanned: number; skipped: ScanSkips }
    | { kind: 'credits-used-up' }
    | ScanFailure

export type AfterClickingScanState =
    | ScanBlockedState
    | { kind: 'loading-sessions' }
    | { kind: 'sessions-error' }
    | { kind: 'no-sessions' }
    | { kind: 'questions'; sessionCount: number; hasMore: boolean }
    | { kind: 'scanning'; done: number; total: number; skipped: ScanSkips }
    | ScanOutcomeState

const BLOCKED_KINDS: AfterClickingScanState['kind'][] = [
    'not-main-environment',
    'no-access',
    'link-tagging-off',
    'sensitive-email',
]
const OUTCOME_KINDS: AfterClickingScanState['kind'][] = [
    'finished',
    'credits-used-up',
    'ai-analysis-not-allowed',
    'scan-error',
]

export function isScanBlocked(state: AfterClickingScanState): state is ScanBlockedState {
    return BLOCKED_KINDS.includes(state.kind)
}

export function isScanOutcome(state: AfterClickingScanState): state is ScanOutcomeState {
    return OUTCOME_KINDS.includes(state.kind)
}

export function scanPrompt(question: string): string {
    return `At some point in this session the person clicked a link in an email and landed on a page whose URL has a ph_workflow_run parameter. Look only at what they did from that page on, and answer this question: ${question}`
}

function scanFailureFrom(error: unknown): ScanFailure {
    if (error instanceof ApiError && error.code === AI_CONSENT_REQUIRED_CODE) {
        return { kind: 'ai-analysis-not-allowed' }
    }
    const detail = error instanceof ApiError && (error.status === 400 || error.status === 403) ? error.detail : null
    return { kind: 'scan-error', message: detail ?? "Replay vision couldn't scan these sessions. Try again." }
}

function isSettled(session: ObservationRequestSessionApi): boolean {
    return session.state !== 'pending' && session.state !== 'running'
}

function sessionFate(session: ObservationRequestSessionApi): SessionFate {
    switch (session.scan_outcome) {
        case 'skipped_limit':
            return 'busy'
        case 'skipped_quota':
            return 'quota'
        case 'skipped_scanner_limit':
            return 'questionLimit'
        case 'failed':
            return 'unscannable'
    }
    // A session with no recording to watch, or whose scan never got an outcome, settles without being watched.
    if (session.state === 'ineligible' || (session.scan_outcome === null && session.state === 'failed')) {
        return 'unscannable'
    }
    return 'scanned'
}

function scanSkips(request: ObservationRequestApi): ScanSkips {
    const skips: ScanSkips = { busy: 0, quota: 0, questionLimit: 0, unscannable: 0 }
    for (const session of request.sessions) {
        const fate = sessionFate(session)
        if (fate !== 'scanned') {
            skips[fate] += 1
        }
    }
    return skips
}

function scanRequestState(request: ObservationRequestApi): AfterClickingScanState {
    const total = request.sessions.length
    if (total > 0 && request.sessions.every((session) => session.scan_outcome === 'skipped_quota')) {
        return { kind: 'credits-used-up' }
    }
    const started = request.sessions.filter((session) => sessionFate(session) === 'scanned')
    const skipped = scanSkips(request)
    if (request.status === 'completed') {
        const withResult = started.filter((session) => session.state === 'succeeded').length
        return { kind: 'finished', withResult, scanned: started.length, skipped }
    }
    return { kind: 'scanning', done: started.filter(isSettled).length, total: started.length, skipped }
}

function isTransient(error: unknown): boolean {
    return !(error instanceof ApiError) || !error.status || error.status >= 500
}

function scanBlockedState(
    currentTeam: TeamPublicType | TeamType | null,
    linkTagging: LinkTagging
): ScanBlockedState | null {
    // Scan requests live in the project's main environment, and the API refuses them from any other.
    if (currentTeam?.project_id && currentTeam.id !== currentTeam.project_id) {
        return { kind: 'not-main-environment' }
    }
    const reason = getReplayVisionEditDisabledReason()
    if (reason) {
        return { kind: 'no-access', reason }
    }
    if (linkTagging === 'off') {
        return { kind: 'link-tagging-off' }
    }
    if (linkTagging === 'sensitive-email') {
        return { kind: 'sensitive-email' }
    }
    return null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface afterClickingScanLogicValues {
    currentTeam: TeamPublicType | TeamType | null // emailImpactLogic
    currentTeamId: number | null // emailImpactLogic
    days: number // emailImpactLogic
    linkTagging: LinkTagging // emailImpactLogic
    askedQuestion: AskedQuestion | null
    customQuestion: string
    scanFailure: ScanFailure | null
    scanRequest: ObservationRequestApi | null
    scanRequestLoading: boolean
    scanStarting: boolean
    scanState: AfterClickingScanState
    sessions: TransactionalEmailImpactSessionsApi | null
    sessionsFailed: boolean
    sessionsLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface afterClickingScanLogicActions {
    setDays: (days: number) => {
        days: number
    } // emailImpactLogic
    askQuestion: (
        question: string,
        questionKey: string | null
    ) => {
        idempotencyKey: string
        question: string
        questionKey: string | null
    }
    loadSessions: (_: void) => void
    loadSessionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSessionsSuccess: (
        sessions: TransactionalEmailImpactSessionsApi,
        payload?: void
    ) => {
        sessions: TransactionalEmailImpactSessionsApi
        payload?: void
    }
    refreshScan: (_: void) => void
    refreshScanFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    refreshScanSuccess: (
        scanRequest: ObservationRequestApi | null,
        payload?: void
    ) => {
        scanRequest: ObservationRequestApi | null
        payload?: void
    }
    resetScan: () => any
    resetScanFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    resetScanSuccess: (
        scanRequest: null,
        payload?: any
    ) => {
        scanRequest: null
        payload?: any
    }
    retryScan: () => {
        value: true
    }
    setCustomQuestion: (customQuestion: string) => {
        customQuestion: string
    }
    startScan: (_: void) => void
    startScanFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    startScanSuccess: (
        scanRequest: ObservationRequestApi | null,
        payload?: void
    ) => {
        scanRequest: ObservationRequestApi | null
        payload?: void
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface afterClickingScanLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        scanState: (
            currentTeam: TeamPublicType | TeamType | null,
            linkTagging: LinkTagging,
            sessions: TransactionalEmailImpactSessionsApi | null,
            sessionsLoading: boolean,
            sessionsFailed: boolean,
            scanRequest: ObservationRequestApi | null,
            scanStarting: boolean,
            scanFailure: ScanFailure | null
        ) => AfterClickingScanState
    }
}

export type afterClickingScanLogicType = MakeLogicType<
    afterClickingScanLogicValues,
    afterClickingScanLogicActions,
    EmailImpactLogicProps,
    afterClickingScanLogicMeta
>

export const afterClickingScanLogic = kea<afterClickingScanLogicType>([
    props({} as EmailImpactLogicProps),
    key((props) => props.workflowId),
    path((key) => ['products', 'workflows', 'frontend', 'Transactional', 'impact', 'afterClickingScanLogic', key]),
    connect((props: EmailImpactLogicProps) => ({
        values: [emailImpactLogic(props), ['currentTeamId', 'currentTeam', 'days', 'linkTagging']],
        actions: [emailImpactLogic(props), ['setDays']],
    })),
    actions({
        askQuestion: (question: string, questionKey: string | null) => ({
            question,
            questionKey,
            idempotencyKey: uuid(),
        }),
        setCustomQuestion: (customQuestion: string) => ({ customQuestion }),
        retryScan: true,
    }),
    loaders(({ props, values, cache }) => ({
        sessions: [
            null as TransactionalEmailImpactSessionsApi | null,
            {
                loadSessions: async (_: void, breakpoint) => {
                    try {
                        const sessions = await transactionalEmailLogImpactSessionsRetrieve(
                            String(values.currentTeamId),
                            {
                                workflow_id: props.workflowId,
                                date_from: dayjs()
                                    .subtract(values.days * 24, 'hour')
                                    .toISOString(),
                            }
                        )
                        breakpoint()
                        return sessions
                    } catch (error) {
                        // A newer list replaced this one, so its failure belongs to a period nobody looks at.
                        breakpoint()
                        throw error
                    }
                },
            },
        ],
        scanRequest: [
            null as ObservationRequestApi | null,
            {
                startScan: async (_: void, breakpoint) => {
                    const asked = values.askedQuestion
                    if (!asked || !values.sessions) {
                        return null
                    }
                    try {
                        const request = await visionRequestsCreate(String(values.currentTeamId), {
                            session_ids: values.sessions.sessions.map((session) => session.session_id),
                            inline: { prompt: scanPrompt(asked.question) },
                            reference: `workflows-email:${props.workflowId}`,
                            idempotency_key: asked.idempotencyKey,
                        })
                        breakpoint()
                        return values.askedQuestion === asked ? request : values.scanRequest
                    } catch (error) {
                        // A newer question started its own scan, so this answer belongs to nobody.
                        breakpoint()
                        if (values.askedQuestion !== asked) {
                            return values.scanRequest
                        }
                        throw error
                    }
                },
                refreshScan: async (_: void, breakpoint) => {
                    const current = values.scanRequest
                    if (!current) {
                        return null
                    }
                    try {
                        const request = await visionRequestsRetrieve(String(values.currentTeamId), current.id)
                        breakpoint()
                        if (values.scanRequest !== current) {
                            return values.scanRequest
                        }
                        cache.pollFailures = 0
                        return request
                    } catch (error) {
                        // A newer poll or retry already took over, so this answer belongs to nobody.
                        breakpoint()
                        if (values.scanRequest !== current) {
                            return values.scanRequest
                        }
                        // The scan keeps running on the server, so a blip in one poll shouldn't end it here.
                        cache.pollFailures = (cache.pollFailures ?? 0) + 1
                        if (isTransient(error) && cache.pollFailures < MAX_POLL_FAILURES) {
                            return current
                        }
                        throw error
                    }
                },
                resetScan: () => null,
            },
        ],
    })),
    reducers({
        askedQuestion: [
            null as AskedQuestion | null,
            {
                askQuestion: (_, asked) => asked,
                resetScan: () => null,
            },
        ],
        customQuestion: ['', { setCustomQuestion: (_, { customQuestion }) => customQuestion }],
        scanStarting: [
            false,
            {
                startScan: () => true,
                startScanSuccess: () => false,
                startScanFailure: () => false,
                resetScan: () => false,
            },
        ],
        sessionsFailed: [
            false,
            { loadSessions: () => false, loadSessionsSuccess: () => false, loadSessionsFailure: () => true },
        ],
        scanFailure: [
            null as ScanFailure | null,
            {
                startScan: () => null,
                refreshScan: () => null,
                resetScan: () => null,
                startScanFailure: (_, { errorObject }) => scanFailureFrom(errorObject),
                refreshScanFailure: (_, { errorObject }) => scanFailureFrom(errorObject),
            },
        ],
    }),
    selectors({
        scanState: [
            (s) => [
                s.currentTeam,
                s.linkTagging,
                s.sessions,
                s.sessionsLoading,
                s.sessionsFailed,
                s.scanRequest,
                s.scanStarting,
                s.scanFailure,
            ],
            (
                currentTeam: TeamPublicType | TeamType | null,
                linkTagging: LinkTagging,
                sessions: TransactionalEmailImpactSessionsApi | null,
                sessionsLoading: boolean,
                sessionsFailed: boolean,
                scanRequest: ObservationRequestApi | null,
                scanStarting: boolean,
                scanFailure: ScanFailure | null
            ): AfterClickingScanState => {
                const blocked = scanBlockedState(currentTeam, linkTagging)
                if (blocked) {
                    return blocked
                }
                if (scanFailure) {
                    return scanFailure
                }
                if (scanRequest) {
                    return scanRequestState(scanRequest)
                }
                if (scanStarting) {
                    return {
                        kind: 'scanning',
                        done: 0,
                        total: sessions?.sessions.length ?? 0,
                        skipped: { busy: 0, quota: 0, questionLimit: 0, unscannable: 0 },
                    }
                }
                if (sessionsFailed) {
                    return { kind: 'sessions-error' }
                }
                if (sessionsLoading || !sessions) {
                    return { kind: 'loading-sessions' }
                }
                if (sessions.sessions.length === 0) {
                    return { kind: 'no-sessions' }
                }
                return { kind: 'questions', sessionCount: sessions.sessions.length, hasMore: sessions.has_more }
            },
        ],
    }),
    listeners(({ actions, values, cache }) => {
        const follow = (request: ObservationRequestApi | null): void => {
            if (!request) {
                return
            }
            if (request.status === 'running') {
                cache.disposables.add(() => {
                    const timer = setTimeout(() => actions.refreshScan(), SCAN_POLL_INTERVAL_MS)
                    return () => clearTimeout(timer)
                }, 'scanPoll')
                return
            }
            // The plugin restarts a registered timer when the tab comes back, which would poll a finished scan.
            cache.disposables.dispose('scanPoll')
            if (cache.finishedRequestId === request.id) {
                return
            }
            cache.finishedRequestId = request.id
            const state = scanRequestState(request)
            const skipped = scanSkips(request)
            posthog.capture('transactional email impact scan finished', {
                sessions: request.sessions.length,
                sessions_with_result: state.kind === 'finished' ? state.withResult : 0,
                sessions_skipped: skipped.busy + skipped.quota + skipped.questionLimit + skipped.unscannable,
                credits_used_up: skipped.quota > 0,
            })
        }
        const reportFailure = (): void => {
            cache.disposables.dispose('scanPoll')
            posthog.capture('transactional email impact scan failed', { reason: values.scanFailure?.kind })
        }
        return {
            askQuestion: ({ questionKey }) => {
                posthog.capture('transactional email impact question asked', {
                    source: questionKey ? 'suggested' : 'custom',
                    question_key: questionKey,
                    sessions: values.sessions?.sessions.length ?? 0,
                    days: values.days,
                })
                actions.startScan()
            },
            startScanSuccess: ({ scanRequest }) => follow(scanRequest),
            refreshScanSuccess: ({ scanRequest }) => follow(scanRequest),
            startScanFailure: reportFailure,
            refreshScanFailure: reportFailure,
            retryScan: () => {
                cache.pollFailures = 0
                if (values.scanRequest) {
                    actions.refreshScan()
                } else {
                    actions.startScan()
                }
            },
            resetScan: () => {
                cache.disposables.dispose('scanPoll')
                cache.pollFailures = 0
            },
            setDays: () => {
                actions.resetScan()
                actions.loadSessions()
            },
        }
    }),
    afterMount(({ actions }) => actions.loadSessions()),
])
