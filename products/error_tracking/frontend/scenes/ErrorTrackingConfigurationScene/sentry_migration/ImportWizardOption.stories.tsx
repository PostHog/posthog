import { Meta, StoryObj } from '@storybook/react'

import { CardGroup } from '@posthog/quill'

import { ImportWizardOption } from './ImportWizardOption'

const meta: Meta<typeof ImportWizardOption> = {
    title: 'ErrorTracking/ImportWizardOption',
    component: ImportWizardOption,
    parameters: {
        layout: 'padded',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof ImportWizardOption>

/** An option with an icon, a plain option, and a selected option. */
export const Variants: Story = {
    render: () => (
        <CardGroup size="sm" className="w-120">
            <ImportWizardOption
                title="Sentry"
                description="Inbound filters and client key rate limits"
                icon={<img src="/static/services/sentry.png" alt="" className="size-8 shrink-0" />}
                onClick={() => {}}
                dataAttr="story-sentry"
            />
            <ImportWizardOption
                title="Sentry cloud"
                description="sentry.io, in the US or EU region"
                onClick={() => {}}
                dataAttr="story-cloud"
            />
            <ImportWizardOption
                title="Self-hosted"
                description="Your own Sentry server"
                selected
                onClick={() => {}}
                dataAttr="story-self-hosted"
            />
        </CardGroup>
    ),
}
