import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { clearRepoIdCache } from '../lib/repoIds'
import { visualReviewRepoLogic } from './visualReviewRepoLogic'

describe('visualReviewRepoLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/visual_review/repos/': [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
            },
        })
        initKeaTests()
        clearRepoIdCache()
    })

    it('marks a repo missing from the project as not found without reporting it', async () => {
        const captureException = jest.spyOn(posthog, 'captureException')
        const logic = visualReviewRepoLogic({ repoFullName: 'example/missing' })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['setRepoNotFound', 'loadRepoSuccess'])
            .toMatchValues({ repoNotFound: true, repo: null })
        expect(captureException).not.toHaveBeenCalled()

        logic.unmount()
    })
})
