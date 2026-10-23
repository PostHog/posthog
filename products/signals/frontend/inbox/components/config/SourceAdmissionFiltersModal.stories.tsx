import type { Meta, StoryObj } from '@storybook/react'

import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../../types'
import { SourceAdmissionFiltersModal } from './SourceAdmissionFiltersModal'

function linearConfig(config: Record<string, any>): SignalSourceConfig {
    return {
        id: 'config-linear-issue',
        source_product: SignalSourceProduct.Linear,
        source_type: SignalSourceType.Issue,
        enabled: true,
        config,
        created_at: '2024-03-20T00:00:00Z',
        updated_at: '2024-03-20T00:00:00Z',
        status: null,
        admission_rule_fields: [
            { field: 'labels', kind: 'string_list' },
            { field: 'priority', kind: 'number' },
            { field: 'state_name', kind: 'string' },
            { field: 'state_type', kind: 'string' },
        ],
    }
}

function ModalHarness({ config }: { config: Record<string, any> }): JSX.Element {
    return <SourceAdmissionFiltersModal sourceConfig={linearConfig(config)} sourceLabel="Linear" onClose={() => {}} />
}

const meta: Meta<typeof ModalHarness> = {
    title: 'Scenes-App/Inbox/SourceAdmissionFiltersModal',
    component: ModalHarness,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-20',
        testOptions: { waitForSelector: '[data-attr="signal-source-admission-filters-save"]' },
    },
}
export default meta

type Story = StoryObj<typeof ModalHarness>

/** First open: no filters, so every issue is eligible. */
export const NoFiltersYet: Story = {
    args: { config: {} },
}

/** Saved filters on a Linear source scoped to picked teams. */
export const FiltersSet: Story = {
    args: {
        config: {
            linear_team_ids: ['team-a', 'team-b'],
            admission_rules: {
                operator: 'AND',
                rules: [
                    { field: 'labels', operator: 'any', value: ['customer-feedback'] },
                    { field: 'labels', operator: 'none', value: ['internal'] },
                    { field: 'priority', operator: 'in', value: [1, 2] },
                ],
            },
        },
    },
}
