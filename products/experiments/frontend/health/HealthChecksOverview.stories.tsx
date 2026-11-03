import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { userEvent } from 'storybook/test'

import { HealthChecksOverview } from './HealthChecksOverview'
import type { HealthPanelCheck } from './healthPanelChecks'

const DESCRIPTIONS: Partial<Record<HealthPanelCheck['key'], string>> = {
    flag_state:
        "Checks that the feature flag matches the experiment's status. A running experiment needs a flag that is on and serves every variant, or new users stop entering it. Before launch and after the end, a flag that serves variants shows them to users that the results don't count.",
    split_changed_mid_run:
        'Looks for changes to the variant split after users were first exposed. A change can move users who already saw one variant to another, which mixes their behavior across variants and biases the results.',
    no_metric:
        'Checks that a launched experiment has at least one metric. Without a metric, the experiment counts exposures but has nothing to compare the variants on.',
    srm: 'Tests whether exposed users are divided across variants in the percentages of the variant split. A mismatch usually means that assignment or tracking loses or adds users in one variant, which biases the results.',
    multiple_variants_share:
        'Counts the users exposed to more than one variant, which the results leave out. A high share usually means that one person has several IDs, and the variants can then lose different users, which biases the results.',
}

const description = (key: HealthPanelCheck['key']): string =>
    DESCRIPTIONS[key] ?? 'Looks for a problem in the setup of the experiment that can make its results wrong.'

const passed = (key: HealthPanelCheck['key'], name: string): HealthPanelCheck => ({
    key,
    name,
    description: description(key),
    status: 'passed',
    reason: null,
    measurement: null,
})

const skipped = (
    key: HealthPanelCheck['key'],
    name: string,
    status: 'not_applicable' | 'not_checked',
    reason: string
): HealthPanelCheck => ({ key, name, description: description(key), status, reason, measurement: null })

const FLAG_SETUP_CHECKS = [
    passed('flag_state', "Flag state that doesn't match the experiment"),
    passed('flag_variants_mismatch', 'Flag variants not set up'),
    passed('forced_variant_release_condition', 'Release conditions that force a variant'),
]

const meta: Meta<typeof HealthChecksOverview> = {
    title: 'Experiments/HealthChecksOverview',
    component: HealthChecksOverview,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    args: { onFindingActedOn: () => {} },
    decorators: [
        (Story) => (
            <div className="w-96">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof HealthChecksOverview>

export const Draft: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            skipped(
                'split_changed_mid_run',
                'Variant split changes since launch',
                'not_applicable',
                'Runs after launch'
            ),
            skipped('no_metric', 'Metrics not set up', 'not_applicable', 'Runs after launch'),
        ],
        findings: [
            {
                code: 'new_flag_no_traffic',
                subcode: null,
                reason: null,
                severity: 'info',
                title: 'The feature flag has no traffic yet',
                detail: "PostHog hasn't recorded any calls to the linked feature flag yet. The experiment only counts users after your code evaluates the flag, so launch after the flag starts getting traffic. New calls can take up to an hour to show up here.",
                evidence: {},
                actions: [],
            },
        ],
        isDraft: true,
        exposureChecksMissing: false,
    },
}

const found = (key: HealthPanelCheck['key'], name: string): HealthPanelCheck => ({
    key,
    name,
    description: description(key),
    status: 'finding',
    reason: null,
    measurement: null,
})

export const DraftWithEventsNotReceived: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            skipped('no_metric', 'Metrics not set up', 'not_applicable', 'Runs after launch'),
            found('metric_event_not_ingested', 'Metric events not received yet'),
            found('exposure_criteria_cannot_match', "Exposure criteria that can't match"),
        ],
        findings: [
            {
                code: 'metric_event_not_ingested',
                subcode: null,
                reason: null,
                severity: 'info',
                title: "A metric uses an event this project hasn't received",
                detail: 'The primary metric "Revenue" uses the event "purchase_completed", which this project hasn\'t received yet. Until it arrives, the metric can\'t compare the variants. Launch the experiment after your code starts sending it.',
                evidence: {
                    metric_1: 'Revenue',
                    metric_1_role: 'primary',
                    metric_1_events: 'purchase_completed',
                },
                actions: [],
            },
            {
                code: 'exposure_criteria_cannot_match',
                subcode: 'exposure_event_not_ingested',
                reason: null,
                severity: 'info',
                title: "This project hasn't received the exposure event",
                detail: 'The experiment counts users as exposed when they send the event "checkout_viewed", which this project hasn\'t received yet. Until it arrives, nobody is counted as exposed. Launch the experiment after your code starts sending it.',
                evidence: { event: 'checkout_viewed' },
                actions: ['edit_exposure_criteria'],
            },
        ],
        isDraft: true,
        exposureChecksMissing: false,
    },
}

export const RunningWithSignificanceOnASmallSample: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            passed('no_metric', 'Metrics not set up'),
            found('early_significance', 'Significance on a small sample'),
        ],
        findings: [
            {
                code: 'early_significance',
                subcode: 'below_detectable_effect',
                reason: null,
                severity: 'info',
                title: 'Significant result on a small sample',
                detail: 'The variant "test" shows a +20% difference on the metric "Checkout", which is significant. With 2,000 users so far, the experiment can reliably detect differences of about 38% or more, so this difference may shrink or go away as more users arrive. The running time estimate needs about 3,201 users to detect a 30% difference. Wait for that sample before you decide.',
                evidence: {
                    variant: 'test',
                    observed_effect: 20,
                    detectable_effect: 37.9,
                    minimum_detectable_effect: 30,
                    samples: 2000,
                    planned_samples: 3201,
                },
                actions: [],
            },
        ],
        isDraft: false,
        exposureChecksMissing: false,
    },
}

export const RunningWithMetricWindowsNotComplete: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            passed('no_metric', 'Metrics not set up'),
            found('metrics_not_matured', 'Metric windows not complete yet'),
        ],
        findings: [
            {
                code: 'metrics_not_matured',
                subcode: null,
                reason: null,
                severity: 'info',
                title: "No results yet because the metric windows aren't complete",
                detail: 'The Exposures panel counts users without waiting for these windows. A metric counts a user only after its conversion or retention window has passed, so no primary metric has results yet. The first users can count for "Checkout" on October 5, 2026 at 2:00 PM CEST and for "Return visits" on October 15, 2026 at 2:00 PM CEST. To see results sooner, turn off "Require completed conversion or retention window" in the experiment\'s Settings tab. Users whose window is still open then count too.',
                evidence: { hours_since_launch: 72, first_users_count_at: '2026-10-05T12:00:00+00:00' },
                actions: [],
            },
        ],
        isDraft: false,
        exposureChecksMissing: false,
    },
}

export const ChecksThatCouldNotRun: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            skipped(
                'split_changed_mid_run',
                'Variant split changes since launch',
                'not_checked',
                "Couldn't check because you can't view the linked feature flag's history"
            ),
            passed('no_metric', 'Metrics not set up'),
        ],
        findings: [],
        isDraft: false,
        exposureChecksMissing: true,
    },
}

export const RunningWithAnIssue: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            passed('no_metric', 'Metrics not set up'),
            found('srm', 'Split of users across variants'),
        ],
        findings: [
            {
                code: 'srm',
                subcode: null,
                reason: null,
                severity: 'warning',
                title: 'Users are not split across variants as configured',
                detail: "The distribution of users across variants doesn't match your configured rollout percentages (p < 0.001). This may indicate issues with randomization or data collection.",
                evidence: { p_value: 0.0002 },
                actions: [],
            },
        ],
        isDraft: false,
        exposureChecksMissing: false,
    },
}

export const CheckDetailsWithAMeasurement: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            passed('no_metric', 'Metrics not set up'),
            {
                ...passed('srm', 'Split of users across variants'),
                measurement: { value: 0.71, threshold: 0.001, unit: 'p_value', warns: 'below' },
            },
            {
                ...passed('multiple_variants_share', 'Users exposed to multiple variants'),
                measurement: { value: 4.2, threshold: 5, unit: 'percentage', warns: 'above' },
            },
        ],
        findings: [],
        isDraft: false,
        exposureChecksMissing: false,
    },
    play: async ({ canvasElement }) => {
        await userEvent.click(
            await within(canvasElement).findByRole('button', { name: /Users exposed to multiple variants/ })
        )
    },
}

export const CheckDetailsOfACheckThatDoesNotApply: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            skipped(
                'split_changed_mid_run',
                'Variant split changes since launch',
                'not_applicable',
                'Runs after launch'
            ),
        ],
        findings: [],
        isDraft: true,
        exposureChecksMissing: false,
    },
    play: async ({ canvasElement }) => {
        await userEvent.click(
            await within(canvasElement).findByRole('button', { name: /Variant split changes since launch/ })
        )
    },
}
