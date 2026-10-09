import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { VisualReviewSettingsScene } from './VisualReviewSettingsScene'

const GITHUB_REPOS = Array.from({ length: 150 }, (_, i) => {
    const name = `repo-${String(i + 1).padStart(3, '0')}`
    return { id: i + 1, name, full_name: `example-org/${name}` }
})

describe('VisualReviewSettingsScene', () => {
    let createdRepoBody: unknown

    beforeEach(() => {
        createdRepoBody = null
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [
                    200,
                    {
                        count: 1,
                        next: null,
                        results: [
                            {
                                id: 7,
                                kind: 'github',
                                display_name: 'example-org',
                                config: { installation_id: '1', repository_selection: 'all' },
                            },
                        ],
                    },
                ],
                '/api/projects/:team_id/integrations/:id/github_repos/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const search = params.get('search') ?? ''
                    const limit = Number(params.get('limit') ?? 100)
                    const offset = Number(params.get('offset') ?? 0)
                    const matches = GITHUB_REPOS.filter((repo) => repo.full_name.includes(search))
                    return [
                        200,
                        {
                            repositories: matches.slice(offset, offset + limit),
                            has_more: offset + limit < matches.length,
                            total: matches.length,
                        },
                    ]
                },
                '/api/projects/:team_id/visual_review/repos/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
            },
            post: {
                '/api/projects/:team_id/visual_review/repos/': async ({ request }) => {
                    createdRepoBody = await request.json()
                    return [201, { id: 'new-repo', repo_full_name: 'example-org/repo-150' }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it('adds a repository from beyond the first page of GitHub results', async () => {
        render(
            <Provider>
                <VisualReviewSettingsScene />
            </Provider>
        )

        await userEvent.type(await screen.findByPlaceholderText('Add a repository...'), 'repo-150')
        await userEvent.click(await screen.findByText('example-org/repo-150'))

        await waitFor(() =>
            expect(createdRepoBody).toEqual({ repo_external_id: 150, repo_full_name: 'example-org/repo-150' })
        )
    })
})
