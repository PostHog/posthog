import type { Meta, StoryObj } from '@storybook/react'

import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../../types'
import { SourceSteeringModal } from './SourceSteeringModal'

function sourceConfig(config: Record<string, any>): SignalSourceConfig {
    return {
        id: 'config-github-issue',
        source_product: SignalSourceProduct.Github,
        source_type: SignalSourceType.Issue,
        enabled: true,
        config,
        created_at: '2024-03-20T00:00:00Z',
        updated_at: '2024-03-20T00:00:00Z',
        status: null,
    }
}

interface HarnessProps {
    config: Record<string, any>
}

function ModalHarness({ config }: HarnessProps): JSX.Element {
    return <SourceSteeringModal sourceConfig={sourceConfig(config)} sourceLabel="GitHub issues" onClose={() => {}} />
}

const meta: Meta<typeof ModalHarness> = {
    title: 'Scenes-App/Inbox/SourceSteeringModal',
    component: ModalHarness,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-20',
        testOptions: { waitForSelector: '[data-attr="signal-source-steering-rules"]' },
    },
}
export default meta

type Story = StoryObj<typeof ModalHarness>

/** First open: nothing written yet. */
export const NoRulesYet: Story = {
    args: { config: {} },
}

/** Editing saved guidance. */
export const RulesSet: Story = {
    args: {
        config: {
            steering: 'Ignore issues labeled chore or internal. Anything mentioning billing is always actionable.',
        },
    },
}

/** A source still carrying the retired posture flag, which the gate keeps honoring. */
export const LegacyPosture: Story = {
    args: { config: { default_not_actionable: true } },
}
