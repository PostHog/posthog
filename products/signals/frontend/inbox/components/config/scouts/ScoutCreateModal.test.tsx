import { cleanup, render } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ScoutCreateModal } from './ScoutCreateModal'

describe('ScoutCreateModal', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
                '/api/projects/:team_id/integrations/github/available_installations/': () => [
                    200,
                    { installations: [], personal_github_connected: false },
                ],
            },
        })
    })

    afterEach(cleanup)

    it('includes tags and a Slack destination in the create form', async () => {
        const { findAllByText, findByLabelText, findByText } = render(
            <ScoutCreateModal
                isOpen
                onClose={jest.fn()}
                initialValues={{
                    name: 'signals-scout-ai-observability-daily-digest',
                    description: 'Creates a daily AI observability digest.',
                    body: 'Review AI observability and create one actionable digest.',
                }}
            />
        )

        expect(await findByText('Slack destination')).toBeTruthy()
        expect(await findByText('Connect a Slack workspace')).toBeTruthy()
        expect(await findByText('Scout details')).toBeTruthy()
        expect(await findAllByText('Instructions')).toHaveLength(2)
        expect(await findByText('Run schedule')).toBeTruthy()
        expect(await findByText('Connections')).toBeTruthy()
        expect(await findByText('Tags')).toBeTruthy()
        expect(await findByLabelText('Instructions')).toBeTruthy()
    })

    it('offers GitHub setup when requested and the project is not connected', async () => {
        const { findByText } = render(
            <ScoutCreateModal
                isOpen
                onClose={jest.fn()}
                showGitHubConnection
                githubSetupNextUrl="/experiments/123?createScout=experiment"
                initialValues={{
                    name: 'signals-scout-experiment-123',
                    description: 'Monitors experiment 123.',
                    body: 'Monitor experiment 123.',
                }}
            />
        )

        expect(await findByText('GitHub connection')).toBeTruthy()
        expect(await findByText('Connect account')).toBeTruthy()
    })
})
