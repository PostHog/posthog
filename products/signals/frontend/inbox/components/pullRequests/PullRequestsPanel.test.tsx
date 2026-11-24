/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper. */
import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PRBrowserItemApi } from 'products/signals/frontend/generated/api.schemas'

import { pullRequestsLogic } from '../../logics/pullRequestsLogic'
import { PullRequestsPanel } from './PullRequestsPanel'

const makePR = (number: number, overrides: Partial<PRBrowserItemApi> = {}): PRBrowserItemApi => ({
    url: `https://github.com/example/widget/pull/${number}`,
    repository: 'example/widget',
    number,
    title: `Change ${number}`,
    state: 'open',
    draft: false,
    author: 'example-author',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    report: null,
    ...overrides,
})

describe('PullRequestsPanel', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('disables Monitor and Retry on closed unmerged PRs while keeping GitHub and report links', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/pull_requests/': {
                    results: [
                        makePR(1, { state: 'closed', draft: true, title: 'Abandoned experiment' }),
                        makePR(2, {
                            state: 'closed',
                            title: 'Closed failed check',
                            report: { id: 'rep-2', status: 'failed' },
                        }),
                        makePR(3, {
                            state: 'closed',
                            title: 'Closed existing report',
                            report: { id: 'rep-3', status: 'suppressed' },
                        }),
                        makePR(4, { state: 'open', title: 'Active change' }),
                        makePR(5, {
                            state: 'open',
                            title: 'Needs instrumentation retry',
                            report: { id: 'rep-5', status: 'pending_input' },
                        }),
                        makePR(6, {
                            state: 'merged',
                            title: 'Old merged change',
                            monitoring_disabled_reason:
                                'Pull requests merged more than 90 days ago are outside the monitoring window',
                        }),
                    ],
                    github_login: 'example-author',
                    has_integration: true,
                },
            },
        })

        const logic = pullRequestsLogic()
        logic.mount()
        render(<PullRequestsPanel />)
        await expectLogic(logic).toDispatchActions(['loadPullRequestsSuccess'])

        const monitorButtons = screen.getAllByText('Monitor').map((node) => node.closest('button'))
        expect(monitorButtons).toHaveLength(3)
        expect(monitorButtons[0]).toHaveAttribute('aria-disabled', 'true')
        expect(monitorButtons[1]).not.toHaveAttribute('aria-disabled', 'true')
        expect(monitorButtons[2]).toHaveAttribute('aria-disabled', 'true')

        expect(screen.queryByText('Draft')).not.toBeInTheDocument()
        expect(screen.getAllByText('Closed')).toHaveLength(3)
        const retryButtons = screen.getAllByText('Retry').map((node) => node.closest('button'))
        expect(retryButtons).toHaveLength(2)
        expect(retryButtons[0]).toHaveAttribute('aria-disabled', 'true')
        expect(retryButtons[1]).not.toHaveAttribute('aria-disabled', 'true')
        expect(screen.getByText('Needs instrumentation retry').closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining('rep-5')
        )
        expect(screen.getByText('Closed existing report').closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining('rep-3')
        )
        expect(screen.getByLabelText('Open example/widget#1 on GitHub')).toHaveAttribute(
            'href',
            'https://github.com/example/widget/pull/1'
        )
        logic.unmount()
    })
})
