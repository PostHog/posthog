import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../../types'
import { ErrorTrackingIssueFiltersModal } from './ErrorTrackingIssueFiltersModal'

function errorTrackingConfigs(config: Record<string, any>): SignalSourceConfig[] {
    return [SignalSourceType.IssueCreated, SignalSourceType.IssueReopened, SignalSourceType.IssueSpiking].map(
        (sourceType) => ({
            id: `config-${sourceType}`,
            source_product: SignalSourceProduct.ErrorTracking,
            source_type: sourceType,
            enabled: true,
            config,
            created_at: '2024-03-20T00:00:00Z',
            updated_at: '2024-03-20T00:00:00Z',
            status: null,
        })
    )
}

function ModalHarness({ config }: { config: Record<string, any> }): JSX.Element {
    return <ErrorTrackingIssueFiltersModal sourceConfigs={errorTrackingConfigs(config)} onClose={() => {}} />
}

const meta: Meta<typeof ModalHarness> = {
    title: 'Scenes-App/Inbox/ErrorTrackingIssueFiltersModal',
    component: ModalHarness,
    decorators: [
        mswDecorator({
            post: {
                '/api/projects/:team_id/signals/source_configs/issue_filter_preview/': () => [
                    200,
                    {
                        status: 'ok',
                        error: null,
                        results: [
                            {
                                source_type: 'issue_created',
                                passing_count: 3,
                                excluded_count: 2,
                                unavailable_count: 1,
                                passing: [],
                                excluded: [],
                                excluded_reports: { count: 2, with_pr: 1, with_merged_pr: 1 },
                            },
                            ...['issue_reopened', 'issue_spiking'].map((source_type) => ({
                                source_type,
                                passing_count: 1,
                                excluded_count: 0,
                                unavailable_count: 0,
                                passing: [],
                                excluded: [],
                                excluded_reports: { count: 0, with_pr: 0, with_merged_pr: 0 },
                            })),
                        ],
                    },
                ],
            },
            get: {
                '/api/environments/:team_id/quick_filters/': { results: [] },
                '/api/projects/:team_id/quick_filters/': { results: [] },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-20',
        testOptions: { waitForSelector: '[data-attr="issue-filter-preview-results"]' },
    },
}
export default meta

type Story = StoryObj<typeof ModalHarness>

/** First open: every issue can reach the inbox. */
export const NoFiltersYet: Story = {
    args: { config: {} },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}

/** Saved filters at a narrow width, so the controls have to wrap. */
export const FiltersSetNarrow: Story = {
    args: {
        config: {
            issue_filters: {
                properties: [
                    { key: '$environment', type: 'event', operator: 'exact', value: ['production'] },
                    { key: 'name', type: 'event', operator: 'icontains', value: 'timeout' },
                    { key: 'severity', type: 'event', operator: 'exact', value: ['high'] },
                ],
            },
        },
    },
    parameters: { testOptions: { viewport: { width: 520, height: 900 } } },
}
