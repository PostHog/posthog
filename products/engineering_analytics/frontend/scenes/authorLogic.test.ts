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

    it('names the repository in the breadcrumbs and keeps the scope on the way back to its overview', () => {
        router.actions.push(urls.engineeringAnalyticsAuthor('jane-dev', 'PostHog/posthog-js'), {
            source: 'source-2',
            date_from: '-30d',
        })
        logic = authorLogic({ handle: 'jane-dev', sourceId: 'source-2', repo: 'PostHog/posthog-js' })
        logic.mount()

        const [product, repository] = logic.values.breadcrumbs
        expect(repository.name).toBe('PostHog/posthog-js')
        const overview = new URL(product.path!, 'https://example.com')
        expect(overview.pathname).toBe('/engineering-analytics/repos/PostHog/posthog-js/overview')
        expect(Object.fromEntries(overview.searchParams)).toEqual({ date_from: '-30d', source: 'source-2' })
    })
})
