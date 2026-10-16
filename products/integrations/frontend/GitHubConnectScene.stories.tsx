import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { GitHubConnectScene } from './GitHubConnectScene'

type ConnectState = 'install' | 'link-existing' | 'connected'

interface StoryArgs {
    state: ConnectState
}

const DISCOVERY = {
    discovery_id: '11111111-1111-4111-8111-111111111111',
    discovered_at: '2026-01-01T00:00:00Z',
    personal_github_connected: true,
    personal_github_login: 'synthetic-reader',
    personal_discovery_status: 'ok',
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Integrations/GitHub connect',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    args: { state: 'install' },
    render: ({ state }): JSX.Element => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations': {
                    results:
                        state === 'connected'
                            ? [
                                  {
                                      id: 1,
                                      kind: 'github',
                                      display_name: 'synthetic-owner',
                                      icon_url: '',
                                      config: { account: { name: 'synthetic-owner' } },
                                      created_at: '2026-01-01T00:00:00Z',
                                  },
                              ]
                            : [],
                },
                '/api/projects/:id/integrations/github/available_installations/': {
                    ...DISCOVERY,
                    installations:
                        state === 'link-existing'
                            ? [
                                  {
                                      installation_id: '9001',
                                      account_name: 'synthetic-owner',
                                      account_type: 'Organization',
                                      source_team_id: 7,
                                      source_team_name: 'Synthetic website',
                                  },
                              ]
                            : [],
                },
            },
        })
        return <GitHubConnectScene />
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const ContinueToGitHub: Story = {}
export const LinkExistingInstallation: Story = { args: { state: 'link-existing' } }
export const AlreadyConnected: Story = { args: { state: 'connected' } }
