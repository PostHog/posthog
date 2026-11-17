import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeReviewApprovalRepositoryApi } from '../../generated/api.schemas'
import { REPOS_PAGE_SIZE, stamphogSceneLogic } from './stamphogSceneLogic'

describe('stamphogSceneLogic', () => {
    let logic: ReturnType<typeof stamphogSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/code_review/approvals/repositories/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                '/api/projects/:team_id/code_review/approvals/repositories/available_repositories/': {
                    repositories: [],
                    total_count: 0,
                    has_installation: true,
                },
                '/api/projects/:team_id/code_review/approvals/repositories/install_info/': {
                    app_slug: 'example-app',
                    install_url: 'https://github.com/apps/example-app/installations/new',
                    authorize_url: 'https://github.com/login/oauth/authorize',
                },
            },
        })
        initKeaTests()
        logic = stamphogSceneLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens the digest history from the URL and drops its params on close', () => {
        router.actions.push(urls.codeReview(), { tab: 'approval_settings', digests: '1', digests_page: '2' })
        expect(logic.values.digestHistoryOpen).toBe(true)

        logic.actions.closeDigestHistory()
        expect(router.values.searchParams).toEqual({ tab: 'approval_settings' })

        router.actions.push(urls.codeReview(), { tab: 'approval_settings', digests: '1' })
        expect(logic.values.digestHistoryOpen).toBe(true)
        router.actions.push(urls.codeReview(), { tab: 'approval_settings' })
        expect(logic.values.digestHistoryOpen).toBe(false)
    })

    it('moves back a page when an update empties the last page of the filtered list', () => {
        const repos = Array.from(
            { length: REPOS_PAGE_SIZE + 1 },
            (_, index) =>
                ({
                    id: `repo-${index}`,
                    repository: `example-org/repo-${index}`,
                    enabled: true,
                }) as CodeReviewApprovalRepositoryApi
        )
        logic.actions.loadRepoConfigsSuccess(repos)
        logic.actions.setRepoView('approving')
        logic.actions.setRepoPage(1)
        expect(logic.values.visibleRepoConfigs).toHaveLength(1)

        logic.actions.loadRepoConfigsSuccess(
            repos.map((repo, index) => (index === REPOS_PAGE_SIZE ? { ...repo, enabled: false } : repo))
        )
        expect(logic.values.repoPage).toBe(0)
        expect(logic.values.visibleRepoConfigs).toHaveLength(REPOS_PAGE_SIZE)
    })

    it('checks only a few owners files at once', () => {
        logic.actions.loadRepoConfigsSuccess(
            Array.from(
                { length: 10 },
                (_, index) =>
                    ({
                        id: `repo-${index}`,
                        repository: `example-org/repo-${index}`,
                        enabled: true,
                    }) as CodeReviewApprovalRepositoryApi
            )
        )
        expect(Object.values(logic.values.ownersFileChecks).filter((status) => status === 'checking')).toHaveLength(4)
    })
})
