import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { myClaim, teammateClaim } from '../../__mocks__/inboxMocks'
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

    // A bulk claim must skip reports a person already holds. A report that changed after the list loaded
    // comes back 409, and its row must then show the current holder and section, not offer the claim again.
    it.each([
        { conflict: 'a teammate claimed it', holder: teammateClaim, status: SignalReportStatus.READY, moved: false },
        { conflict: 'it was resolved', holder: null, status: SignalReportStatus.RESOLVED, moved: true },
    ])('claims only the unclaimed reports and reconciles one that $conflict', async ({ holder, status, moved }) => {
        const claimed: string[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/': ({ params }) => [
                    200,
                    { id: params.id, assignee: holder, status },
                ],
            },
            post: {
                '/api/projects/:team_id/signals/reports/:id/claim/': ({ params }) => {
                    claimed.push(String(params.id))
                    return params.id === 'c'
                        ? [409, {}]
                        : [200, { id: params.id, assignee: myClaim, updated_at: '2026-06-11T11:00:00Z' }]
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
            .toDispatchActions([
                logic.actionCreators.reportClaimsChanged([
                    { reportId: 'a', assignee: myClaim },
                    { reportId: 'c', assignee: holder },
                ]),
                ...(moved ? ['reportStateChanged'] : []),
                'bulkClaimSuccess',
            ])
            .toMatchValues({ selectedReportIds: [] })
        if (!moved) {
            await expectLogic(logic).toNotHaveDispatchedActions(['reportStateChanged'])
        }
        expect(claimed.sort()).toEqual(['a', 'c'])
    })
})
