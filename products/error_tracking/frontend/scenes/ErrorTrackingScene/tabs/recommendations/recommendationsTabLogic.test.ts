import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { LongRunningIssueItem, LongRunningIssuesRecommendation } from './types'

const issue = (id: string, status: 'active' | 'suppressed' = 'active'): LongRunningIssueItem => ({
    id,
    name: `issue ${id}`,
    description: null,
    created_at: '2026-01-01T00:00:00Z',
    occurrences: 1,
    status,
})

const longRunningRecommendation = (issues: LongRunningIssueItem[]): LongRunningIssuesRecommendation => ({
    id: 'rec-long-running',
    type: 'long_running_issues',
    meta: { issues },
    completed: false,
    status: 'ready',
    computed_at: '2026-01-01T00:00:00Z',
    dismissed_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

describe('recommendationsTabLogic', () => {
    let logic: ReturnType<typeof recommendationsTabLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.errorTracking, 'listRecommendations').mockResolvedValue({ results: [] })
        logic = recommendationsTabLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    const seededIssues = (): LongRunningIssueItem[] =>
        (logic.values.recommendations[0] as LongRunningIssuesRecommendation).meta.issues

    // The background auto-merge can delete an issue that a card still shows. Suppressing it 404s.
    // That used to throw an unhandled error; it must now drop the stale row and clear the spinner.
    it('drops the stale issue and does not refetch when suppress hits a 404', async () => {
        logic.actions.setRecommendations([longRunningRecommendation([issue('gone'), issue('stays')])])
        jest.spyOn(api.errorTracking, 'updateIssue').mockRejectedValue({ status: 404 })
        const refresh = jest.spyOn(api.errorTracking, 'refreshRecommendation')

        await expectLogic(logic, () => {
            logic.actions.suppressIssue('gone')
        }).toDispatchActions(['startIssueMutation', 'upsertRecommendation', 'finishIssueMutation'])

        expect(refresh).not.toHaveBeenCalled()
        expect(seededIssues().map((i) => i.id)).toEqual(['stays'])
        expect(logic.values.pendingIssueIds.has('gone')).toBe(false)
    })

    // A merged-away issue stays in the backend's enriched meta until the next recompute, so a poll
    // can re-list an issue the user already dropped after a 404. That phantom row must not reappear
    // in the displayed recommendations.
    it('keeps a dropped stale issue out of the displayed list when a later poll re-lists it', async () => {
        logic.actions.setRecommendations([longRunningRecommendation([issue('gone'), issue('stays')])])
        jest.spyOn(api.errorTracking, 'updateIssue').mockRejectedValue({ status: 404 })

        await expectLogic(logic, () => {
            logic.actions.suppressIssue('gone')
        }).toDispatchActions(['markIssueStale', 'finishIssueMutation'])

        // The next poll returns server data that still lists the deleted issue.
        jest.spyOn(api.errorTracking, 'listRecommendations').mockResolvedValue({
            results: [longRunningRecommendation([issue('gone'), issue('stays')])],
        })

        await expectLogic(logic, () => {
            logic.actions.pollRecommendations()
        }).toDispatchActions(['setRecommendations'])

        const visible = logic.values.activeRecommendations[0] as LongRunningIssuesRecommendation
        expect(visible.meta.issues.map((i) => i.id)).toEqual(['stays'])
    })

    // The button spinner reads from pendingIssueIds; it must clear whether the update succeeds or fails.
    it('clears the pending state after a successful suppress', async () => {
        const recommendation = longRunningRecommendation([issue('one')])
        logic.actions.setRecommendations([recommendation])
        jest.spyOn(api.errorTracking, 'updateIssue').mockResolvedValue({} as any)
        jest.spyOn(api.errorTracking, 'refreshRecommendation').mockResolvedValue({
            ...recommendation,
            meta: { issues: [issue('one', 'suppressed')] },
        })

        await expectLogic(logic, () => {
            logic.actions.suppressIssue('one')
        }).toDispatchActions(['startIssueMutation', 'finishIssueMutation'])

        expect(logic.values.pendingIssueIds.has('one')).toBe(false)
    })
})
