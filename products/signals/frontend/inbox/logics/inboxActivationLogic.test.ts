import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { InboxOnboardingStateApi, ScoutSuggestionSetApi } from '../../generated/api.schemas'
import { mockScoutSuggestionSet } from '../__mocks__/scoutConfigs'
import { inboxActivationLogic } from './inboxActivationLogic'
import { inboxSetupLogic } from './inboxSetupLogic'
import { REFRESH_POLL_TIMEOUT_MS, scoutSuggestionsLogic } from './scoutSuggestionsLogic'

const ACTIVATED_AT = Date.parse('2026-10-01T12:00:00Z')

describe('Inbox activation progress', () => {
    let logic: ReturnType<typeof inboxActivationLogic.build>
    let state: InboxOnboardingStateApi
    let batch: ScoutSuggestionSetApi
    let unmount: () => void
    let stateReads: number

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers({
            doNotFake: ['setTimeout', 'clearTimeout', 'setImmediate', 'clearImmediate', 'nextTick', 'queueMicrotask'],
        })
        jest.setSystemTime(ACTIVATED_AT)
        stateReads = 0
        state = {
            completed_at: new Date(ACTIVATED_AT).toISOString(),
            draft: null,
            jobs: { scout: 'pending', recommendations: 'started' },
        }
        batch = mockScoutSuggestionSet({ generated_at: new Date(ACTIVATED_AT - 60_000).toISOString() })
        useMocks({
            get: {
                '/api/projects/:id/signals/onboarding/': () => {
                    stateReads++
                    return [200, state]
                },
                '/api/projects/:id/signals/scout/suggestions/': () => [200, batch],
                '/api/projects/:id/signals/scout/configs/': [],
                '/api/projects/:id/signals/source_configs/': { results: [], next: null },
                '/api/projects/:id/vision/scanners/': { results: [], next: null },
            },
        })
        logic = inboxActivationLogic()
        unmount = logic.mount()
    })

    afterEach(() => {
        unmount()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    async function settle(): Promise<void> {
        await expectLogic(inboxSetupLogic).toFinishAllListeners()
        await expectLogic(scoutSuggestionsLogic).toFinishAllListeners()
    }

    it('hides old recommendations and keeps polling until scout dispatch settles', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        await settle()
        logic.actions.reportRecommendationsShown()
        expect(capture.mock.calls.filter(([event]) => event === 'Scout suggestions shown')).toHaveLength(0)
        expect(logic.values.suggestions).toEqual([])
        batch = { ...batch, generated_at: new Date(ACTIVATED_AT + 1000).toISOString() }
        await jest.advanceTimersByTimeAsync(10_000)
        await settle()
        expect(logic.values.recommendationsReady).toBe(true)
        expect(logic.values.suggestions).toEqual(batch.items)
        logic.actions.reportRecommendationsShown()
        logic.actions.reportRecommendationsShown()
        expect(capture.mock.calls.filter(([event]) => event === 'Scout suggestions shown')).toEqual([
            [
                'Scout suggestions shown',
                expect.objectContaining({
                    surface: 'onboarding',
                    suggestion_count: batch.items.length,
                    inbox_client: 'cloud',
                }),
                undefined,
            ],
        ])
        state = { ...state, jobs: { scout: 'failed', recommendations: 'started' } }
        await jest.advanceTimersByTimeAsync(10_000)
        await settle()
        expect(logic.values.savedState?.jobs?.scout).toBe('failed')
        const settledReads = stateReads
        await jest.advanceTimersByTimeAsync(20_000)
        await settle()
        expect(stateReads).toBe(settledReads)
    })

    it.each([
        ['a failed recommendation generation', { scout: 'started', recommendations: 'failed' }],
        ['a completed setup without a jobs record', undefined],
    ] as const)('stops polling %s without showing the previous batch', async (_name, jobs) => {
        await settle()
        state = { ...state, jobs }
        await jest.advanceTimersByTimeAsync(10_000)
        await settle()
        expect(logic.values.savedState?.jobs?.recommendations).toBe(jobs?.recommendations)
        expect(logic.values.suggestions).toEqual([])
        const readsAfterFailure = stateReads
        await jest.advanceTimersByTimeAsync(20_000)
        await settle()
        expect(stateReads).toBe(readsAfterFailure)
        expect(logic.values.pollingExpired).toBe(false)
    })

    it('polls beyond fifteen minutes and reads once more at the workflow deadline', async () => {
        await settle()
        jest.setSystemTime(ACTIVATED_AT + 20 * 60_000)
        await jest.advanceTimersByTimeAsync(10_000)
        await settle()
        expect(logic.values.pollingExpired).toBe(false)
        const readsBeforeDeadline = stateReads
        batch = { ...batch, generated_at: new Date(ACTIVATED_AT + 30 * 60_000).toISOString() }
        jest.setSystemTime(ACTIVATED_AT + REFRESH_POLL_TIMEOUT_MS)
        await jest.advanceTimersByTimeAsync(10_000)
        await settle()
        expect(stateReads).toBe(readsBeforeDeadline + 1)
        expect(logic.values.suggestions).toEqual(batch.items)
        expect(logic.values.pollingExpired).toBe(true)
        await jest.advanceTimersByTimeAsync(20_000)
        expect(stateReads).toBe(readsBeforeDeadline + 1)
    })

    it('follows the first report after activation settles and stops when the investigation finishes', async () => {
        await settle()
        state = {
            ...state,
            jobs: { scout: 'started', recommendations: 'skipped' },
            first_report: { status: 'pending' },
        }
        await jest.advanceTimersByTimeAsync(10_000)
        await settle()
        state = {
            ...state,
            first_report: {
                status: 'running',
                task_id: '11111111-1111-4111-8111-111111111111',
                task_run_id: '22222222-2222-4222-8222-222222222222',
            },
        }
        await jest.advanceTimersByTimeAsync(20_000)
        await settle()
        expect(logic.values.savedState?.first_report).toEqual(state.first_report)
        state = { ...state, first_report: { status: 'insufficient_data', missing_data: ['No completed signups yet.'] } }
        await jest.advanceTimersByTimeAsync(10_000)
        await settle()
        expect(logic.values.savedState?.first_report).toEqual(state.first_report)
        const completedReads = stateReads
        await jest.advanceTimersByTimeAsync(20_000)
        await settle()
        expect(stateReads).toBe(completedReads)
    })
})
