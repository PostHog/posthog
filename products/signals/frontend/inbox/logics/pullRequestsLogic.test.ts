import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from 'products/signals/frontend/generated/api'
import type { PRBrowserItemApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringTabLogic } from './monitoringTabLogic'
import { pullRequestsLogic } from './pullRequestsLogic'

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

describe('pullRequestsLogic', () => {
    let logic: ReturnType<typeof pullRequestsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(api, 'signalsPullRequestsList').mockResolvedValue({
            results: [
                makePR(1, { state: 'open' }),
                makePR(2, { state: 'merged', report: { id: 'rep-2', status: 'monitoring' } }),
                makePR(3, { state: 'merged', report: { id: 'rep-3', status: 'failed' } }),
            ],
            github_login: 'example-author',
            has_integration: true,
        })
        jest.spyOn(api, 'signalsReportsList').mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('filters loaded PRs client-side by monitoring and GitHub state without refetching', async () => {
        logic = pullRequestsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPullRequestsSuccess'])

        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([1, 2, 3])

        logic.actions.setFilter('unmonitored')
        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([1])

        logic.actions.setFilter('monitored')
        logic.actions.setStateFilter('merged')
        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([2, 3])

        logic.actions.setFilter('all')
        logic.actions.setStateFilter('open')
        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([1])
        expect(api.signalsPullRequestsList).toHaveBeenCalledTimes(1)
    })

    it('starts monitoring in one click, updates the PR report status, and refreshes the monitoring list', async () => {
        const monitor = jest.spyOn(api, 'signalsMonitorPrCreate').mockResolvedValue({
            report_id: '01950000-0000-7000-8000-000000000001',
            report_url: 'http://localhost:8000/project/997/inbox/reports/01950000-0000-7000-8000-000000000001',
            status: 'in_progress',
            idempotent_replay: false,
        })
        const monitoringLogic = monitoringTabLogic()
        monitoringLogic.mount()
        const loadReportsSpy = jest.spyOn(monitoringLogic.actions, 'loadReports')

        logic = pullRequestsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPullRequestsSuccess'])

        const targetUrl = 'https://github.com/example/widget/pull/1'
        logic.actions.monitorPR(targetUrl)
        await expectLogic(logic).toDispatchActions(['monitorPRDone'])

        expect(monitor).toHaveBeenCalledWith('997', { pr_url: targetUrl })
        expect(logic.values.page?.results[0].report).toEqual({
            id: '01950000-0000-7000-8000-000000000001',
            status: 'in_progress',
        })
        expect(loadReportsSpy).toHaveBeenCalled()
        monitoringLogic.unmount()
    })

    it('skips loading PRs while collapsed, loads when expanded, and retries failed research', async () => {
        const monitor = jest.spyOn(api, 'signalsMonitorPrCreate').mockResolvedValue({
            report_id: 'rep-3',
            report_url: 'http://localhost:8000/project/997/inbox/reports/rep-3',
            status: 'in_progress',
            idempotent_replay: false,
        })
        localStorage.setItem('products.signals.inbox.pullRequestsLogic.panelOpen', JSON.stringify(false))

        logic = pullRequestsLogic()
        logic.mount()
        expect(logic.values.panelOpen).toBe(false)
        expect(api.signalsPullRequestsList).not.toHaveBeenCalled()

        logic.actions.setPanelOpen(true)
        await expectLogic(logic).toDispatchActions(['loadPullRequestsSuccess'])
        expect(api.signalsPullRequestsList).toHaveBeenCalledTimes(1)

        logic.actions.monitorPR('https://github.com/example/widget/pull/3')
        await expectLogic(logic).toDispatchActions(['monitorPRDone'])
        expect(monitor).toHaveBeenCalledWith('997', { pr_url: 'https://github.com/example/widget/pull/3' })
        expect(logic.values.page?.results[2].report?.status).toBe('in_progress')
    })
})
