import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { stamphogSceneLogic } from './stamphogSceneLogic'

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
})
