import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { teammateClaim } from '../../__mocks__/inboxMocks'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, type SignalReport, SignalReportStatus } from '../../types'
import { InboxBulkSelectionBar } from './InboxBulkSelectionBar'

function makeReport(id: string, overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id,
        title: `Report ${id}`,
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: false,
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
        ...overrides,
    }
}

describe('InboxBulkSelectionBar', () => {
    let logic: ReturnType<typeof inboxBulkActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = inboxBulkActionsLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        // The list scope persists to localStorage, so a test that changes it would leak into the next.
        localStorage.clear()
    })

    // The bar holds a count and no titles, so its dialogs have to count reports at every size. The
    // single-report copy would print the "Untitled report" placeholder over a report that has a title.
    it.each([
        { button: 'Dismiss', reportIds: ['a'], heading: 'Dismiss 1 report?' },
        { button: 'Dismiss', reportIds: ['a', 'b'], heading: 'Dismiss 2 reports?' },
        { button: 'Resolve', reportIds: ['a'], heading: 'Resolve 1 report?' },
        { button: 'Resolve', reportIds: ['a', 'b'], heading: 'Resolve 2 reports?' },
    ])(
        '$button counts the selection in its dialog at $reportIds.length selected',
        async ({ button, reportIds, heading }) => {
            logic.actions.setSelectedReportIds(reportIds)
            render(<InboxBulkSelectionBar reports={reportIds.map((id) => makeReport(id))} />)

            fireEvent.click(screen.getByText(button))

            expect(await screen.findByText(heading)).toBeInTheDocument()
        }
    )

    it('warns when bulk dismissal closes a selected pull request', async () => {
        logic.actions.setSelectedReportIds(['a'])
        render(
            <InboxBulkSelectionBar
                reports={[makeReport('a', { implementation_pr_url: 'https://github.com/PostHog/posthog/pull/1' })]}
            />
        )

        fireEvent.click(screen.getByText('Dismiss'))

        expect(await screen.findByText(/The pull request opened for this report is closed/)).toBeInTheDocument()
    })

    it.each([
        { scope: INBOX_SCOPE_ENTIRE_PROJECT, sent: ['b', 'c'], unassigned: ['b'] },
        { scope: INBOX_SCOPE_FOR_YOU, sent: ['a', 'b', 'c'], unassigned: ['a', 'b'] },
    ])('under $scope unassigns $sent and drops only the ones that succeeded', async ({ scope, sent, unassigned }) => {
        const deleted: string[] = []
        useMocks({
            delete: {
                '/api/projects/:team_id/signals/reports/:id/reviewers/me/': ({ params }) => {
                    deleted.push(String(params.id))
                    return params.id === 'c' ? [500, {}] : [204, null]
                },
            },
        })
        inboxFiltersLogic.mount()
        inboxFiltersLogic.actions.setScope(scope)
        logic.actions.setSelectedReportIds(['a', 'b', 'c'])
        render(
            <InboxBulkSelectionBar
                reports={[
                    makeReport('a'),
                    makeReport('b', { is_suggested_reviewer: true }),
                    makeReport('c', { is_suggested_reviewer: true }),
                ]}
            />
        )

        // The button opens the reasons; picking one is what sends the requests.
        fireEvent.click(screen.getByText('Unassign me'))
        await expectLogic(logic, () => {
            fireEvent.click(screen.getByText('Without a reason'))
        })
            .toDispatchActions([logic.actionCreators.unassignedMe(unassigned), 'bulkUnassignMeSuccess'])
            .toMatchValues({ selectedReportIds: [] })
        expect(deleted.sort()).toEqual(sent)
    })

    // A report a person holds must not reach the server, and the whole selection must go in one request.
    it('claims only the claimable reports, in one request', async () => {
        const bodies: unknown[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/signals/reports/bulk_claim/': async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, { results: [], claimed_count: 2, conflict_count: 0, not_found_count: 0 }]
                },
            },
        })
        logic.actions.setSelectedReportIds(['a', 'b', 'c'])
        render(
            <InboxBulkSelectionBar
                reports={[makeReport('a'), makeReport('b', { assignee: teammateClaim }), makeReport('c')]}
            />
        )

        await expectLogic(logic, () => {
            fireEvent.click(screen.getByText('Claim'))
        })
            .toDispatchActions(['bulkClaimSuccess'])
            .toMatchValues({ selectedReportIds: [], isClaiming: false })
        expect(bodies).toEqual([{ ids: ['a', 'c'], takeover_agent_claims: true }])
    })
})
