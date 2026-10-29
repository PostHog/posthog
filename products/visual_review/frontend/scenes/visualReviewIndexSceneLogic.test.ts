import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { clearRepoIdCache } from '../lib/repoIds'
import { visualReviewIndexSceneLogic } from './visualReviewIndexSceneLogic'

const RUN_ID = '00000000-0000-0000-0000-0000000000aa'

describe('visualReviewIndexSceneLogic', () => {
    let releaseRun: () => void = () => {}

    beforeEach(() => {
        const runGate = new Promise<void>((resolve) => {
            releaseRun = resolve
        })
        useMocks({
            get: {
                [`/api/projects/:team_id/visual_review/runs/${RUN_ID}/`]: async () => {
                    await runGate
                    return [200, { id: RUN_ID, repo_id: 'repo' }]
                },
                '/api/projects/:team_id/visual_review/repos/': [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [{ id: 'repo', repo_full_name: 'PostHog/posthog', created_at: '2026-01-01' }],
                    },
                ],
            },
        })
        initKeaTests()
        clearRepoIdCache()
    })

    it.each([
        {
            name: 'forwards an old run link to the owner/name URL',
            leave: false,
            expected: '/visual-review/repos/PostHog/posthog/runs/',
        },
        { name: 'stays on the page the user moved to during the lookup', leave: true, expected: '/settings/project' },
    ])('$name', async ({ leave, expected }) => {
        router.actions.push(`/visual-review/runs/${RUN_ID}`, {}, { snapshot: 'kept' })
        const logic = visualReviewIndexSceneLogic()
        logic.mount()
        logic.actions.forward({ kind: 'run', runId: RUN_ID })
        if (leave) {
            router.actions.push('/settings/project')
        }

        releaseRun()
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.location.pathname).toContain(expected)
        expect(router.values.hashParams).toEqual(leave ? {} : { snapshot: 'kept' })
        logic.unmount()
    })
})
