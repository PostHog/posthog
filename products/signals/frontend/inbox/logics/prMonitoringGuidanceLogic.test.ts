/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper. */
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    PR_MONITORING_NOTE_AUTHOR,
    PR_MONITORING_REPO_REASON,
    isPrMonitoringReport,
    selectVisibleReportActivity,
} from '../components/detail/artefactTypes'
import { SignalReport, SignalReportArtefact, SignalReportStatus } from '../types'
import { inboxReportDetailLogic } from './inboxReportDetailLogic'
import { prMonitoringGuidanceLogic } from './prMonitoringGuidanceLogic'

const PR_URL = 'https://github.com/example/widget/pull/42'

function makeArtefact(overrides: Partial<SignalReportArtefact>): SignalReportArtefact {
    return {
        id: 'art-1',
        report_id: 'rep-1',
        type: 'note',
        actor_kind: 'system',
        content: {},
        created_at: '2026-01-01T00:01:00Z',
        updated_at: '2026-01-01T00:01:00Z',
        ...overrides,
    } as SignalReportArtefact
}

describe('prMonitoringGuidanceLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it('filters internal status rows from activity while surfacing PR monitoring guidance notes', () => {
        const visible = selectVisibleReportActivity([
            makeArtefact({ id: 'a1', type: 'check_authoring', content: { status: 'failed', reason: 'pending' } }),
            makeArtefact({ id: 'a2', type: 'reviewer_corrections', content: {} }),
            makeArtefact({ id: 'a3', type: 'pr_owner_assignment', content: {} }),
            makeArtefact({
                id: 'a4',
                type: 'note',
                actor_kind: 'system',
                content: { note: 'Watch `checkout_started`?', author: PR_MONITORING_NOTE_AUTHOR },
            }),
        ])
        expect(visible.map((row) => row.id)).toEqual(['a4'])

        const prReport = {
            id: 'rep-1',
            status: SignalReportStatus.PENDING_INPUT,
            signal_count: 0,
            summary: 'Post-merge impact check for example/widget#42.',
        } as unknown as SignalReport
        const signalReport = {
            id: 'rep-2',
            status: SignalReportStatus.PENDING_INPUT,
            signal_count: 3,
            summary: 'Checkout latency spiked.',
        } as unknown as SignalReport

        expect(isPrMonitoringReport(prReport, null, true)).toBe(true)
        expect(
            isPrMonitoringReport(
                { ...prReport, summary: 'Edited summary' } as SignalReport,
                [makeArtefact({ type: 'repo_selection', content: { reason: PR_MONITORING_REPO_REASON } })],
                true
            )
        ).toBe(true)
        expect(isPrMonitoringReport(signalReport, [], true)).toBe(false)
    })

    it.each([
        { mode: 'same_report', returnedReportId: 'rep-1' },
        { mode: 'teammate_new_report', returnedReportId: 'rep-2' },
    ])('reads the latest guidance question and submits guidance ($mode)', async ({ returnedReportId }) => {
        const posted: Record<string, unknown>[] = []
        const report = {
            id: 'rep-1',
            status: SignalReportStatus.PENDING_INPUT,
            title: 'Monitor Improve checkout',
            summary: 'Post-merge impact check for example/widget#42.',
            signal_count: 0,
            pull_requests: [{ url: PR_URL, state: 'open', merged: false }],
        } as unknown as SignalReport

        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/feedback_state/': { sentiment: null, note: null },
                '/api/projects/:team_id/signals/reports/:id/signals/': { signals: [] },
                '/api/projects/:team_id/signals/reports/:id/checks/': { results: [] },
                '/api/projects/:team_id/signals/reports/:id/pr_checks/': { checks: [], mergeable_state: 'clean' },
                '/api/projects/:team_id/signals/reports/:id/pr_comments/': { comments: [] },
                '/api/projects/:team_id/signals/available_reviewers/': { results: [] },
                '/api/environments/:team_id/integrations/': { results: [] },
                '/api/projects/:team_id/signals/reports/:id/artefacts/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        makeArtefact({
                            id: 'older',
                            created_at: '2026-01-01T00:01:00Z',
                            content: { note: 'First question', author: PR_MONITORING_NOTE_AUTHOR },
                        }),
                        makeArtefact({
                            id: 'newer',
                            created_at: '2026-01-01T00:05:00Z',
                            content: {
                                note: 'Candidate proxy is `checkout_started`. Which metric should PostHog watch?',
                                author: PR_MONITORING_NOTE_AUTHOR,
                            },
                        }),
                    ],
                },
            },
            post: {
                '/api/projects/:team_id/signals/monitor_pr/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    posted.push(body)
                    return [
                        202,
                        {
                            report_id: returnedReportId,
                            report_url: `http://localhost:8000/project/997/inbox/reports/${returnedReportId}`,
                            status: 'in_progress',
                            idempotent_replay: false,
                        },
                    ]
                },
            },
        })

        const detailLogic = inboxReportDetailLogic({ reportId: 'rep-1', report })
        detailLogic.mount()
        const logic = prMonitoringGuidanceLogic({ reportId: 'rep-1', report })
        logic.mount()

        await expectLogic(detailLogic).toDispatchActions(['loadReportArtefactsSuccess'])
        expect(logic.values.guidanceQuestion).toBe(
            'Candidate proxy is `checkout_started`. Which metric should PostHog watch?'
        )

        logic.actions.setDraftNote('  Watch checkout_started after merge  ')
        logic.actions.submitGuidance(PR_URL)
        await expectLogic(logic).toFinishAllListeners()

        expect(posted).toEqual([{ pr_url: PR_URL, note: 'Watch checkout_started after merge' }])
        expect(logic.values.draftNote).toBe('')
        expect(logic.values.submitting).toBe(false)
        if (returnedReportId === 'rep-1') {
            expect(detailLogic.values.report?.status).toBe(SignalReportStatus.IN_PROGRESS)
            expect(logic.values.guidanceQuestion).toBeNull()
        } else {
            expect(router.values.location.pathname).toContain('rep-2')
        }

        logic.unmount()
        detailLogic.unmount()
    })
})
