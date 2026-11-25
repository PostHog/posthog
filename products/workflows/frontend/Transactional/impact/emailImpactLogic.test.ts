import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'
import { runInThisContext } from 'vm'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import { RUNNING_QUERY_WAIT_LIMIT_MS, emailImpactLogic } from './emailImpactLogic'

const ENVIRONMENT: TeamType = { ...MOCK_DEFAULT_TEAM, id: MOCK_TEAM_ID + 5, project_id: MOCK_TEAM_ID }

const IMPACT: TransactionalEmailImpactApi = {
    sent: 10,
    delivered: 9,
    opened: 5,
    clicked: 2,
    not_clicked: 7,
    untracked: 0,
    clicks_untracked: 0,
    window_days: 7,
    after_click: { sends: 1, converted: 0 },
    without_click: { sends: 7, converted: 1 },
}
const WITHOUT_EVENT: TransactionalEmailImpactApi = { ...IMPACT, after_click: null, without_click: null }

describe('emailImpactLogic', () => {
    let logic: ReturnType<typeof emailImpactLogic.build>
    let requestedFrom: string[]
    let requestedParams: URLSearchParams[]
    let answer: [number, unknown] | Promise<[number, unknown]>
    let onRequest: () => void
    // Running queries are shared across mounts by workflow, so each test gets its own workflow.
    let testCount = 0
    let workflowId: string
    let heldAnswers: ((answer: [number, unknown]) => void)[]

    beforeEach(() => {
        localStorage.clear()
        workflowId = `workflow-${++testCount}`
        heldAnswers = []
        requestedFrom = []
        requestedParams = []
        answer = [200, WITHOUT_EVENT]
        onRequest = () => {}
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/impact/': ({ params, request }) => {
                    requestedFrom.push(String(params.team_id))
                    requestedParams.push(new URL(request.url).searchParams)
                    onRequest()
                    return answer
                },
            },
        })
    })

    afterEach(() => {
        logic.unmount()
        heldAnswers.forEach((finish) => finish([200, WITHOUT_EVENT]))
    })

    it('asks the environment the email belongs to, and says which sends it could follow once an event is picked', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedFrom).toEqual([String(ENVIRONMENT.id)])
        expect(requestedParams[0].get('event')).toBeNull()
        expect(logic.values.impact).toEqual(WITHOUT_EVENT)
        expect(logic.values.followedNote).toBeNull()

        answer = [200, { ...IMPACT, clicks_untracked: 3 }]
        logic.actions.setEvent('plan upgraded')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.followedNote).toMatch(/^Counted over 1 of 2 clicked sends:/)
        expect(capture.mock.calls.filter(([name]) => name === 'transactional email impact loaded')).toEqual([
            [
                'transactional email impact loaded',
                { has_event: false, days: 30, has_untracked_sends: false, has_clicks_untracked_sends: false },
            ],
            [
                'transactional email impact loaded',
                { has_event: true, days: 30, has_untracked_sends: false, has_clicks_untracked_sends: true },
            ],
        ])
    })

    it('loads once the team arrives when the tab mounts first', async () => {
        initKeaTests(true, null as unknown as TeamType)
        logic = emailImpactLogic({ workflowId })
        const requested = new Promise<void>((resolve) => (onRequest = resolve))
        logic.mount()
        await requested
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedFrom).toEqual([String(teamLogic.values.currentTeamId)])
        expect(logic.values.impact).toEqual(WITHOUT_EVENT)
    })

    it.each([
        ['period', (): void => logic.actions.setDays(7), null, 7],
        ['event', (): void => logic.actions.setEvent('plan upgraded'), 'plan upgraded', 30],
    ])('shows the funnel as pending until a new %s answers', async (_, change, event, days) => {
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        let answerNewSends: () => void = () => {}
        answer = new Promise((resolve) => {
            answerNewSends = () => resolve([200, { ...(event ? IMPACT : WITHOUT_EVENT), sent: 4 }])
        })

        const requested = new Promise<void>((resolve) => (onRequest = resolve))

        change()
        await requested

        expect(logic.values.funnelState).toBe('loading')
        const params = requestedParams[requestedParams.length - 1]
        expect(params.get('workflow_id')).toBe(workflowId)
        expect(params.get('event')).toBe(event)
        expect(dayjs().diff(dayjs(params.get('date_from')), 'day')).toBe(days)
        answerNewSends()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.funnelState).toBe('ready')
        expect(logic.values.impact?.sent).toBe(4)
    })

    const holdAnswer = (): ((answer: [number, unknown]) => void) => {
        let finish: (answer: [number, unknown]) => void = () => {}
        answer = new Promise((resolve) => (finish = resolve))
        heldAnswers.push(finish)
        return finish
    }

    const holdNextQuery = async (): Promise<(answer: [number, unknown]) => void> => {
        const finish = holdAnswer()
        const requested = new Promise<void>((resolve) => (onRequest = resolve))
        logic.actions.setDays(7)
        await requested
        return finish
    }

    it.each([
        ['answers', [200, { ...WITHOUT_EVENT, sent: 9 }]],
        ['fails', [500, { detail: 'Server error' }]],
    ])(
        'waits for a running query that %s, then asks once for the latest period and event',
        async (_, runningAnswer) => {
            initKeaTests(true, ENVIRONMENT)
            logic = emailImpactLogic({ workflowId })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const finishRunningQuery = await holdNextQuery()

            jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] })
            try {
                logic.actions.setDays(1)
                await jest.advanceTimersByTimeAsync(500)
                logic.actions.setEvent('plan upgraded')
                await jest.advanceTimersByTimeAsync(500)
                expect(requestedParams).toHaveLength(2)

                const answerReplacement = holdAnswer()
                finishRunningQuery(runningAnswer as [number, unknown])
                await jest.advanceTimersByTimeAsync(500)
                expect(requestedParams).toHaveLength(3)
                expect(logic.values.funnelState).toBe('loading')
                expect(logic.values.impact?.sent).toBe(WITHOUT_EVENT.sent)

                answerReplacement([200, { ...IMPACT, sent: 4 }])
                await jest.advanceTimersByTimeAsync(500)
            } finally {
                jest.useRealTimers()
            }
            await expectLogic(logic).toFinishAllListeners()

            expect(requestedParams).toHaveLength(3)
            expect(requestedParams[2].get('event')).toBe('plan upgraded')
            expect(Math.round(dayjs().diff(dayjs(requestedParams[2].get('date_from')), 'hour', true))).toBe(24)
            expect(logic.values.impact?.sent).toBe(4)
            expect(logic.values.impactError).toBeNull()
        }
    )

    it('waits for the query a closed tab left running when the tab opens again', async () => {
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const finishRunningQuery = await holdNextQuery()

        logic.unmount()
        logic = emailImpactLogic({ workflowId })
        jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] })
        try {
            logic.mount()
            await jest.advanceTimersByTimeAsync(500)
            expect(requestedParams).toHaveLength(2)

            answer = [200, { ...WITHOUT_EVENT, sent: 4 }]
            finishRunningQuery([200, WITHOUT_EVENT])
            await jest.advanceTimersByTimeAsync(500)
        } finally {
            jest.useRealTimers()
        }
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedParams).toHaveLength(3)
        expect(logic.values.impact?.sent).toBe(4)
    })

    it('stops waiting for a query that never answers, and still waits for the query that replaced it', async () => {
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const finishStalledQuery = await holdNextQuery()

        jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'nextTick', 'setImmediate'] })
        try {
            const finishReplacement = holdAnswer()
            logic.actions.setDays(1)
            await jest.advanceTimersByTimeAsync(RUNNING_QUERY_WAIT_LIMIT_MS - 1000)
            expect(requestedParams).toHaveLength(2)
            await jest.advanceTimersByTimeAsync(2000)
            expect(requestedParams).toHaveLength(3)

            finishStalledQuery([200, { ...WITHOUT_EVENT, sent: 9 }])
            await jest.advanceTimersByTimeAsync(500)
            logic.actions.setEvent('plan upgraded')
            await jest.advanceTimersByTimeAsync(500)
            expect(requestedParams).toHaveLength(3)

            answer = [200, { ...IMPACT, sent: 4 }]
            finishReplacement([200, { ...WITHOUT_EVENT, sent: 3 }])
            await jest.advanceTimersByTimeAsync(500)
        } finally {
            jest.useRealTimers()
        }
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedParams).toHaveLength(4)
        expect(requestedParams[3].get('event')).toBe('plan upgraded')
        expect(logic.values.impact?.sent).toBe(4)
    })

    it('asks for the last 24 hours, not one calendar day, the day after the clocks change', async () => {
        // Jest gives each test file its own copy of process.env, so the time zone has to change on Node's process.
        const nodeProcess = runInThisContext('process') as NodeJS.Process
        const timezone = nodeProcess.env.TZ
        nodeProcess.env.TZ = 'Europe/Berlin'
        jest.useFakeTimers({
            now: new Date('2026-03-29T12:00:00Z'),
            doNotFake: [
                'setTimeout',
                'clearTimeout',
                'setInterval',
                'clearInterval',
                'setImmediate',
                'queueMicrotask',
                'nextTick',
            ],
        })
        try {
            initKeaTests(true, ENVIRONMENT)
            logic = emailImpactLogic({ workflowId })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setDays(1)
            await expectLogic(logic).toFinishAllListeners()

            expect(requestedParams[requestedParams.length - 1].get('date_from')).toBe('2026-03-28T12:00:00.000Z')
        } finally {
            jest.useRealTimers()
            nodeProcess.env.TZ = timezone
        }
    })

    it.each([
        [
            "a 403 with the server's reason",
            [403, { detail: 'You need access to querying events to count conversions.' }],
            'You need access to querying events to count conversions.',
        ],
        [
            'a server failure with the shorter-period hint',
            [500, { detail: 'Server error' }],
            "This email's impact couldn't load. Try again, or pick a shorter period.",
        ],
        [
            'a query limit with the wait hint',
            [429, { detail: 'Request was throttled.' }],
            'Too many queries are running right now. Wait a few seconds, then try again.',
        ],
        [
            'a request failure without the shorter-period hint',
            [404, { detail: 'Not found.' }],
            "This email's impact couldn't load. Try again, and if it keeps failing, contact support.",
        ],
    ])('explains %s, and clears it once a retry answers', async (_, response, message) => {
        answer = response as [number, unknown]
        const capture = jest.spyOn(posthog, 'capture')
        initKeaTests(true, ENVIRONMENT)
        logic = emailImpactLogic({ workflowId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.impactError).toBe(message)
        expect(logic.values.funnelState).toBe('error')
        expect(capture).not.toHaveBeenCalledWith('transactional email impact loaded', expect.anything())

        answer = [200, WITHOUT_EVENT]
        logic.actions.loadImpact()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.impactError).toBeNull()
        expect(logic.values.funnelState).toBe('ready')
    })
})
