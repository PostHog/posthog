import { expectLogic } from 'kea-test-utils'

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
            variant: 'test-github',
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
        jest.useRealTimers()
    })

    async function settle(): Promise<void> {
        await expectLogic(inboxSetupLogic).toFinishAllListeners()
        await expectLogic(scoutSuggestionsLogic).toFinishAllListeners()
    }

    it('hides old recommendations and keeps polling until scout dispatch settles', async () => {
        await settle()
        expect(logic.values.suggestions).toEqual([])
        batch = { ...batch, generated_at: new Date(ACTIVATED_AT + 1000).toISOString() }
        await jest.advanceTimersByTimeAsync(10_000)
        await settle()
        expect(logic.values.recommendationsReady).toBe(true)
        expect(logic.values.suggestions).toEqual(batch.items)
        state = { ...state, jobs: { scout: 'failed', recommendations: 'started' } }
        await jest.advanceTimersByTimeAsync(10_000)
        await settle()
        expect(logic.values.savedState?.jobs?.scout).toBe('failed')
        const settledReads = stateReads
        await jest.advanceTimersByTimeAsync(20_000)
        await settle()
        expect(stateReads).toBe(settledReads)
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
})
