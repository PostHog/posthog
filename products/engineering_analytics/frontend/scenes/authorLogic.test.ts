import { router } from 'kea-router'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { engineeringAnalyticsAuthorWorkflowCosts } from '../generated/api'
import { authorLogic } from './authorLogic'

jest.mock('../generated/api', () => ({
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

    it('keeps the scope on the breadcrumbs back to the pull requests list', () => {
        router.actions.push(urls.engineeringAnalyticsAuthor('jane-dev'), {
            source: 'source-2',
            repo: 'PostHog/posthog-js',
            date_from: '-30d',
        })
        logic = authorLogic({ handle: 'jane-dev', sourceId: 'source-2' })
        logic.mount()

        const [hub, pullRequests] = logic.values.breadcrumbs.map(({ path }) => new URL(path!, 'https://example.com'))
        expect(pullRequests.pathname).toBe(
            new URL(urls.engineeringAnalyticsPullRequestList(), 'https://example.com').pathname
        )
        for (const destination of [hub, pullRequests]) {
            expect(Object.fromEntries(destination.searchParams)).toEqual({
                date_from: '-30d',
                source: 'source-2',
                repo: 'PostHog/posthog-js',
            })
        }
    })
})
