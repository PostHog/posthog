import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import * as eaApi from '../generated/api'
import { repoOverviewLogic } from './repoOverviewLogic'

describe('repoOverviewLogic', () => {
    let logic: ReturnType<typeof repoOverviewLogic.build>

    beforeEach(() => {
        initKeaTests()
        // The overview scene mounts engineeringAnalyticsLogic too, which fans out to several reads on
        // mount — stub them all so only the loader under test drives the assertions.
        jest.spyOn(eaApi, 'engineeringAnalyticsRepoOverview').mockResolvedValue({} as any)
        jest.spyOn(eaApi, 'engineeringAnalyticsMasterFailures').mockResolvedValue([] as any)
        jest.spyOn(eaApi, 'engineeringAnalyticsSources').mockResolvedValue([] as any)
        jest.spyOn(eaApi, 'engineeringAnalyticsCiCards').mockResolvedValue({
            open_prs: 0,
            repos: 0,
            stuck: 0,
            failing_ci: 0,
        } as any)
        jest.spyOn(eaApi, 'engineeringAnalyticsPullRequests').mockResolvedValue({ items: [] } as any)
        jest.spyOn(eaApi, 'engineeringAnalyticsWorkflowHealth').mockResolvedValue([] as any)
        jest.spyOn(eaApi, 'engineeringAnalyticsQuarantine').mockResolvedValue({
            available: false,
            entries: [],
            parse_errors: [],
            parse_warnings: [],
            source_url: '',
            repo: null,
        } as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('swallows the not-connected 400 into the empty state instead of failing', async () => {
        // A team with no GitHub source connected gets a deliberate 400 from every read. It must not
        // surface as a loader failure (which the global onFailure captures as an exception) — the
        // shared notConnected state renders the connect prompt instead.
        const notConnected = new ApiError('Connect a GitHub data warehouse source to use engineering analytics.', 400)
        jest.spyOn(eaApi, 'engineeringAnalyticsRepoOverview').mockRejectedValue(notConnected)
        jest.spyOn(eaApi, 'engineeringAnalyticsMasterFailures').mockRejectedValue(notConnected)

        logic = repoOverviewLogic()
        await expectLogic(logic, () => {
            logic.mount()
        })
            .toDispatchActions(['loadOverview', 'loadMasterFailures'])
            .toFinishAllListeners()

        expect(logic.values.overview).toBeNull()
        expect(logic.values.masterFailures).toEqual([])
        expect(logic.values.overviewFailed).toBe(false)
    })

    it('re-throws a genuine (non-400) error so overviewFailed is set', async () => {
        silenceKeaLoadersErrors()
        jest.spyOn(eaApi, 'engineeringAnalyticsRepoOverview').mockRejectedValue(new ApiError('boom', 500))

        logic = repoOverviewLogic()
        await expectLogic(logic, () => {
            logic.mount()
        })
            .toDispatchActions(['loadOverview', 'loadOverviewFailure'])
            .toFinishAllListeners()

        expect(logic.values.overviewFailed).toBe(true)
        resumeKeaLoadersErrors()
    })
})
