import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import * as api from 'products/signals/frontend/generated/api'
import type { PRBrowserOverviewApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringTabLogic } from './monitoringTabLogic'
import { pullRequestsLogic } from './pullRequestsLogic'

const overview = (number: number): PRBrowserOverviewApi => ({
    pull_request: {
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
    },
    body: '',
    head_branch: 'feature',
    base_branch: 'main',
    additions: 1,
    deletions: 0,
    changed_files: 1,
    checks: [],
    checks_available: true,
    has_conflicts: false,
})

describe('pullRequestsLogic', () => {
    let logic: ReturnType<typeof pullRequestsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        router.actions.push(urls.inbox('monitoring'))
        jest.spyOn(api, 'signalsPullRequestsList').mockResolvedValue({
            results: [overview(1).pull_request, overview(2).pull_request],
            next_cursor: null,
            github_login: 'example-author',
            has_integration: true,
            incomplete: false,
        })
        jest.spyOn(api, 'signalsPullRequestsOverviewRetrieve').mockImplementation(async (_, params) =>
            overview(params.pr_url.endsWith('/1') ? 1 : 2)
        )
        logic = pullRequestsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('does not replace the selected PR when an older overview finishes last', async () => {
        let finishFirst!: (value: PRBrowserOverviewApi) => void
        jest.mocked(api.signalsPullRequestsOverviewRetrieve).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finishFirst = resolve
                })
        )
        logic.actions.selectPR(overview(1).pull_request.url)
        await expectLogic(logic, () => logic.actions.selectPR(overview(2).pull_request.url)).toDispatchActions([
            'loadPullRequestOverviewSuccess',
        ])
        finishFirst(overview(1))
        await new Promise<void>((resolve) => setImmediate(resolve))
        expect(logic.values.selectedPR?.number).toBe(2)
        expect(logic.values.overview?.pull_request.number).toBe(2)
    })

    it('passes the optional focus note, updates the PR report status, and refreshes monitoring', async () => {
        let submitted: unknown
        jest.spyOn(api, 'signalsMonitorPrCreate').mockImplementation(async (_, body) => {
            submitted = body
            return {
                report_id: 'report-1',
                report_url: 'https://example.com/report-1',
                status: 'in_progress',
                idempotent_replay: false,
            }
        })
        jest.spyOn(api, 'signalsReportsList').mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        })
        const monitoring = monitoringTabLogic()
        monitoring.mount()
        const loadReportsSpy = jest.spyOn(monitoring.actions, 'loadReports')

        try {
            await expectLogic(logic, () => logic.actions.selectPR(overview(1).pull_request.url)).toDispatchActions([
                'loadPullRequestOverviewSuccess',
            ])
            logic.actions.setNote('  Watch checkout completion.  ')
            await expectLogic(logic, () => logic.actions.monitorPR()).toDispatchActions(['monitorPRSuccess'])

            expect(submitted).toEqual({ pr_url: overview(1).pull_request.url, note: 'Watch checkout completion.' })
            expect(logic.values.selectedPR?.report).toEqual({ id: 'report-1', status: 'in_progress' })
            expect(loadReportsSpy).toHaveBeenCalled()
        } finally {
            monitoring.unmount()
        }
    })

    it('opens the panel on deep link, preserves pr_filter without duplicate page loads, and retries failed research', async () => {
        logic.unmount()
        jest.mocked(api.signalsPullRequestsList).mockClear()
        const failedOverview: PRBrowserOverviewApi = {
            ...overview(1),
            pull_request: {
                ...overview(1).pull_request,
                report: { id: 'report-failed', status: 'failed' },
            },
        }
        jest.mocked(api.signalsPullRequestsOverviewRetrieve).mockResolvedValueOnce(failedOverview)
        jest.spyOn(api, 'signalsMonitorPrCreate').mockResolvedValueOnce({
            report_id: 'report-failed',
            report_url: 'https://example.com/report-failed',
            status: 'in_progress',
            idempotent_replay: false,
        })

        // Persist collapsed state before deep-linking to a PR on the Monitoring tab.
        window.localStorage.setItem('products.signals.inbox.pullRequestsLogic.panelOpen', 'false')
        router.actions.push(urls.inbox('monitoring'), {
            pr_filter: 'monitored',
            pr: failedOverview.pull_request.url,
        })
        logic = pullRequestsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPullRequestOverviewSuccess'])
        expect(logic.values.panelOpen).toBe(true)
        expect(logic.values.filter).toBe('monitored')
        expect(router.values.searchParams.pr_filter).toBe('monitored')
        expect(api.signalsPullRequestsList).toHaveBeenCalledTimes(1)

        await expectLogic(logic, () => logic.actions.monitorPR()).toDispatchActions(['monitorPRSuccess'])
        expect(logic.values.overview?.pull_request.report?.status).toBe('in_progress')
    })

    it('skips loading PRs while the panel starts collapsed and loads when expanded', async () => {
        logic.unmount()
        jest.mocked(api.signalsPullRequestsList).mockClear()
        window.localStorage.setItem('products.signals.inbox.pullRequestsLogic.panelOpen', 'false')
        router.actions.push(urls.inbox('monitoring'))

        logic = pullRequestsLogic()
        logic.mount()
        expect(logic.values.panelOpen).toBe(false)
        expect(api.signalsPullRequestsList).not.toHaveBeenCalled()

        await expectLogic(logic, () => logic.actions.togglePanel()).toDispatchActions(['loadPullRequestsSuccess'])
        expect(logic.values.panelOpen).toBe(true)
        expect(api.signalsPullRequestsList).toHaveBeenCalledTimes(1)
    })
})
