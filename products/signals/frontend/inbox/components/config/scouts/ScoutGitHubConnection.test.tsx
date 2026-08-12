import { cleanup, render, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ScoutGitHubConnection } from './ScoutGitHubConnection'

describe('ScoutGitHubConnection', () => {
    afterEach(cleanup)

    it('offers GitHub setup when the project has no GitHub integration', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': { results: [] },
                '/api/projects/:team_id/integrations/github/available_installations/': {
                    installations: [],
                    personal_github_connected: false,
                },
            },
        })
        initKeaTests()

        const { findByText } = render(
            <ScoutGitHubConnection githubSetupNextUrl="/experiments/123?createScout=experiment" />
        )

        expect(await findByText('GitHub connection')).toBeTruthy()
        expect(await findByText('Connect account')).toBeTruthy()
    })

    it('does not show GitHub setup when the project is connected', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': {
                    results: [
                        {
                            id: 7,
                            kind: 'github',
                            display_name: 'example-org',
                            config: {},
                            created_at: '2026-08-12T00:00:00Z',
                        },
                    ],
                },
            },
        })
        initKeaTests()

        const { queryByText } = render(<ScoutGitHubConnection />)

        await waitFor(() => expect(queryByText('GitHub connection')).toBeNull())
        expect(queryByText('Connect account')).toBeNull()
    })
})
