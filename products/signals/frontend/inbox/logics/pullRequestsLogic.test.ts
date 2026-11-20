import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from 'products/signals/frontend/generated/api'
import type { PRBrowserOverviewApi } from 'products/signals/frontend/generated/api.schemas'

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
        initKeaTests()
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
            'loadOverviewSuccess',
        ])
        finishFirst(overview(1))
        await new Promise<void>((resolve) => setImmediate(resolve))
        expect(logic.values.selectedPR?.number).toBe(2)
        expect(logic.values.overview?.pull_request.number).toBe(2)
    })

    it('passes the optional focus note and opens the returned report', async () => {
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
        jest.spyOn(api, 'signalsReportsRetrieve').mockImplementation(() => new Promise(() => {}))
        await expectLogic(logic, () => logic.actions.selectPR(overview(1).pull_request.url)).toDispatchActions([
            'loadOverviewSuccess',
        ])
        logic.actions.setNote('  Watch checkout completion.  ')
        await expectLogic(logic, () => logic.actions.monitorPR()).toDispatchActions([
            'monitorPRSuccess',
            'setDetailTab',
        ])
        expect(submitted).toEqual({ pr_url: overview(1).pull_request.url, note: 'Watch checkout completion.' })
        expect(logic.values.detailTab).toBe('report')
    })
})
