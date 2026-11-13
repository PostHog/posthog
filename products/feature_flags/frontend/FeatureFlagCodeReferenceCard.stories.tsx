import { Meta, StoryObj } from '@storybook/react'

import { FeatureFlagCodeReferenceCard } from './FeatureFlagCodeReferenceCard'

const meta: Meta<typeof FeatureFlagCodeReferenceCard> = {
    title: 'Scenes-App/Feature Flags/Code Reference Card',
    component: FeatureFlagCodeReferenceCard,
    args: {
        repository: 'example-org/storefront',
        commitSha: '3f9c2a1b7d4e5f60718293a4b5c6d7e8f9012345',
        onGitHubLinkClick: () => {},
    },
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        (Story) => (
            <div className="max-w-4xl">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof FeatureFlagCodeReferenceCard>

export const OnAndOff: Story = {
    args: {
        reference: {
            file: 'frontend/src/checkout/CheckoutSummary.tsx',
            check_line: 42,
            method: 'useFeatureFlagEnabled',
            summary: 'Shows the redesigned plan summary instead of the invoice table.',
            branches: [
                {
                    variant: 'enabled',
                    start_line: 43,
                    end_line: 48,
                    snippet: [
                        '            return (',
                        '                <PlanSummary',
                        '                    plan={plan}',
                        '                    onUpgrade={() => openUpgradeModal(plan.id)}',
                        '                />',
                        '            )',
                    ].join('\n'),
                },
                {
                    variant: 'disabled',
                    start_line: 50,
                    end_line: 50,
                    snippet: '            return <InvoiceTable invoices={invoices} />',
                },
            ],
        },
    },
}

export const Multivariate: Story = {
    args: {
        reference: {
            file: 'billing/pricing.py',
            check_line: 118,
            method: 'get_feature_flag',
            summary: 'Picks which pricing page layout a visitor gets.',
            branches: [
                {
                    variant: 'test',
                    start_line: 121,
                    end_line: 122,
                    snippet: '        layout = "compact"\n        show_annual_toggle = True',
                },
                { variant: 'disabled', start_line: 126, end_line: 126, snippet: '' },
                { variant: 'control', start_line: 119, end_line: 119, snippet: '        layout = "classic"' },
            ],
        },
    },
}

export const EveryOutcome: Story = {
    args: {
        reference: {
            file: 'frontend/src/theme/applyTheme.ts',
            check_line: 17,
            method: 'isFeatureEnabled',
            summary: 'Adds the high-contrast class to the page when the flag turns on.',
            branches: [
                {
                    variant: 'all',
                    start_line: 17,
                    end_line: 17,
                    snippet: "    document.body.classList.toggle('theme-high-contrast', isOn)",
                },
            ],
        },
    },
}
