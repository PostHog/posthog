import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { SourceFilterCatalogApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../../types'
import { SourceFilterModal } from './SourceFilterModal'

const CATALOG: SourceFilterCatalogApi = {
    source_product: 'linear',
    source_type: 'issue',
    catalog_version: 2,
    filter_fields: [
        { name: 'team_id', type: 'string', description: 'ID of the Linear team the issue belongs to.' },
        {
            name: 'project_name',
            type: 'string',
            description: "Name of the issue's project. Null when the issue has no project.",
        },
        {
            name: 'assignee_id',
            type: 'string',
            description: 'ID of the user assigned to the issue. Null when the issue is unassigned.',
        },
        {
            name: 'label_names',
            type: 'array<string>',
            description: "Names of the issue's labels. Empty when the issue has no labels.",
        },
        {
            name: 'priority',
            type: 'integer',
            description: 'Priority of the issue: 0 is no priority, 1 is urgent, 2 is high, 3 is normal and 4 is low.',
        },
    ],
    starter_expressions: ['assignee_id IS NULL', "NOT has(label_names, 'internal')"],
}

function linearConfig(config: Record<string, any>): SignalSourceConfig {
    return {
        id: 'config-linear-issue',
        source_product: SignalSourceProduct.Linear,
        source_type: SignalSourceType.Issue,
        enabled: true,
        config,
        created_at: '2026-11-01T00:00:00Z',
        updated_at: '2026-11-01T00:00:00Z',
        status: null,
    }
}

const LINEAR_INTEGRATION = {
    id: 7,
    kind: 'linear',
    display_name: 'Example workspace',
    icon_url: '/static/services/linear.png',
    config: {},
    created_at: '2026-11-01T00:00:00Z',
}

const LINEAR_TEAMS = [
    { id: 'team-eng', name: 'Engineering' },
    { id: 'team-design', name: 'Design' },
    { id: 'team-support', name: 'Support' },
]

const meta: Meta<typeof SourceFilterModal> = {
    title: 'Scenes-App/Inbox/SourceFilterModal',
    component: SourceFilterModal,
    args: { catalog: CATALOG, sourceLabel: 'Linear', onClose: () => {} },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations/': { results: [LINEAR_INTEGRATION] },
                '/api/environments/:team_id/integrations/:id/linear_teams/': { teams: LINEAR_TEAMS },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-11-16',
        featureFlags: [FEATURE_FLAGS.SIGNALS_SOURCE_FILTERS],
        testOptions: { waitForSelector: '[data-attr="signal-source-filter-save"]', snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof SourceFilterModal>

export const NoFilterYet: Story = {
    args: { sourceConfig: linearConfig({}) },
}

export const EditingAFilter: Story = {
    args: {
        sourceConfig: linearConfig({
            hogql_filter: {
                expression: "assignee_id IS NULL AND priority IN (1, 2) AND NOT has(label_names, 'internal')",
                catalog_version: 2,
            },
        }),
    },
}

export const SavedOnAnOlderFieldList: Story = {
    args: {
        sourceConfig: linearConfig({ hogql_filter: { expression: "project_name = 'Mobile app'", catalog_version: 1 } }),
    },
}

export const WithPickedTeams: Story = {
    args: {
        sourceConfig: linearConfig({
            linear_team_ids: ['team-eng', 'team-support'],
            hogql_filter: { expression: "NOT has(label_names, 'internal')", catalog_version: 2 },
        }),
    },
}
