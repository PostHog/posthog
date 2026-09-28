import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../../types'
import { LinearTeamsModal } from './LinearTeamsModal'

function sourceConfig(config: Record<string, any>, enabled = true): SignalSourceConfig {
    return {
        id: 'config-linear-issue',
        source_product: SignalSourceProduct.Linear,
        source_type: SignalSourceType.Issue,
        enabled,
        config,
        created_at: '2024-03-20T00:00:00Z',
        updated_at: '2024-03-20T00:00:00Z',
        status: null,
    }
}

const LINEAR_INTEGRATION = {
    id: 7,
    kind: 'linear',
    display_name: 'Example workspace',
    icon_url: '/static/services/linear.png',
    config: {},
    created_at: '2024-03-20T00:00:00Z',
}

const LINEAR_TEAMS = [
    { id: 'team-eng', name: 'Engineering' },
    { id: 'team-design', name: 'Design' },
    { id: 'team-support', name: 'Support' },
]

interface HarnessProps {
    config: SignalSourceConfig | null
    enableOnSave: boolean
}

function ModalHarness({ config, enableOnSave }: HarnessProps): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/integrations/': { results: [LINEAR_INTEGRATION] },
            '/api/environments/:team_id/integrations/:id/linear_teams/': { teams: LINEAR_TEAMS },
        },
    })
    return <LinearTeamsModal config={config} enableOnSave={enableOnSave} viaSetupWizard={false} onClose={() => {}} />
}

const meta: Meta<typeof ModalHarness> = {
    title: 'Scenes-App/Inbox/LinearTeamsModal',
    component: ModalHarness,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-20',
        testOptions: { waitForSelector: '[data-attr="signal-source-linear-teams-save"]' },
    },
}
export default meta

type Story = StoryObj<typeof ModalHarness>

export const EnableFlow: Story = {
    args: { config: null, enableOnSave: true },
}

export const TeamsPicked: Story = {
    args: { config: sourceConfig({ linear_team_ids: ['team-eng', 'team-support'] }), enableOnSave: false },
}
