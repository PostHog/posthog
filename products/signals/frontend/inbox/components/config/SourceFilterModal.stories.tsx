import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type {
    SourceFilterCatalogApi,
    SourceFilterPreviewRecordApi,
    SourceFilterPreviewResponseApi,
} from 'products/signals/frontend/generated/api.schemas'

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
    preview_supported: true,
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

function issue(number: number, title: string, createdAt: string): SourceFilterPreviewRecordApi {
    return {
        id: `issue-${number}`,
        identifier: `ENG-${number}`,
        title,
        url: `https://linear.app/example/issue/ENG-${number}`,
        created_at: createdAt,
        malformed: false,
        field_values: {},
        failed_conditions: null,
    }
}

const PASSING = [
    issue(2481, 'Checkout button unresponsive on Safari 18', '2026-11-15T22:00:00Z'),
    issue(2479, 'Export to CSV drops rows past 10k', '2026-11-15T19:00:00Z'),
    issue(2477, 'Push notifications arrive twice on Android', '2026-11-15T13:00:00Z'),
    issue(2473, 'Dark mode contrast too low on settings page', '2026-11-14T17:00:00Z'),
    issue(2470, 'Search results ignore accented characters', '2026-11-13T17:00:00Z'),
]

const EXCLUDED = [
    issue(2480, 'Bump eslint plugin to latest', '2026-11-15T21:00:00Z'),
    issue(2478, 'Investigate flaky billing test', '2026-11-15T16:00:00Z'),
    issue(2474, 'Q4 planning doc review', '2026-11-14T22:00:00Z'),
    issue(2471, 'Rotate staging database credentials', '2026-11-14T02:00:00Z'),
]

function preview(filtered: boolean): SourceFilterPreviewResponseApi {
    return {
        status: 'ok',
        error: null,
        error_code: null,
        error_start: null,
        error_end: null,
        catalog_version: 2,
        lookback_days: 7,
        total_count: 64,
        passing_count: filtered ? 38 : 64,
        excluded_count: filtered ? 26 : 0,
        malformed_count: 0,
        passing: filtered ? PASSING : [...PASSING, ...EXCLUDED],
        excluded: filtered ? EXCLUDED : [],
    }
}

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
            post: {
                '/api/projects/:team_id/signals/source_configs/filter_validate/': {
                    valid: true,
                    catalog_version: 2,
                    error: null,
                    error_code: null,
                    error_start: null,
                    error_end: null,
                },
                '/api/projects/:team_id/signals/source_configs/filter_preview/': async ({ request }) => {
                    const { expression } = (await request.json()) as { expression: string }
                    return [200, preview(!!expression.trim())]
                },
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

export const SourceWithoutPreview: Story = {
    args: {
        catalog: { ...CATALOG, preview_supported: false },
        sourceConfig: linearConfig({
            hogql_filter: { expression: "NOT has(label_names, 'internal')", catalog_version: 2 },
        }),
    },
}
