import { router } from 'kea-router'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { engineeringAnalyticsAuthorWorkflowCosts } from '../generated/api'
import { authorLogic } from './authorLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsAuthorFrictionDetail: jest.fn().mockResolvedValue(null),
    engineeringAnalyticsAuthorWorkflowCosts: jest.fn(),
}))

const mockWorkflowCosts = engineeringAnalyticsAuthorWorkflowCosts as jest.MockedFunction<
    typeof engineeringAnalyticsAuthorWorkflowCosts
>

describe('authorLogic', () => {
    let logic: ReturnType<typeof authorLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        mockWorkflowCosts.mockResolvedValue([])
    })

    afterEach(() => logic?.unmount())

    it('keeps the repository and scope on the breadcrumbs back to the pull requests list', () => {
        router.actions.push(urls.engineeringAnalyticsAuthor('jane-dev', 'PostHog/posthog-js'), {
            source: 'source-2',
            date_from: '-30d',
        })
        logic = authorLogic({ handle: 'jane-dev', sourceId: 'source-2', repo: 'PostHog/posthog-js' })
        logic.mount()

        const [hub, pullRequests] = logic.values.breadcrumbs.map(({ path }) => new URL(path!, 'https://example.com'))
        expect(hub.pathname).toBe('/engineering-analytics/repos/PostHog/posthog-js/overview')
        expect(pullRequests.pathname).toBe('/engineering-analytics/repos/PostHog/posthog-js/pull-requests')
        for (const destination of [hub, pullRequests]) {
            expect(Object.fromEntries(destination.searchParams)).toEqual({ date_from: '-30d', source: 'source-2' })
        }
    })
})
