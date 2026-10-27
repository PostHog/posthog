import type { Meta, StoryObj } from '@storybook/react'

import { HealthChecksOverview } from './HealthChecksOverview'
import type { HealthPanelCheck } from './healthPanelChecks'

const passed = (key: HealthPanelCheck['key'], name: string): HealthPanelCheck => ({
    key,
    name,
    status: 'passed',
    reason: null,
})

const skipped = (
    key: HealthPanelCheck['key'],
    name: string,
    status: 'not_applicable' | 'not_checked',
    reason: string
): HealthPanelCheck => ({ key, name, status, reason })

const FLAG_SETUP_CHECKS = [
    passed('flag_state', 'Feature flag rollout'),
    passed('flag_variants_mismatch', 'Feature flag variants'),
    passed('forced_variant_release_condition', 'Release conditions that force a variant'),
]

const meta: Meta<typeof HealthChecksOverview> = {
    title: 'Experiments/HealthChecksOverview',
    component: HealthChecksOverview,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof HealthChecksOverview>

export const Draft: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            skipped('flag_history', 'Feature flag history', 'not_applicable', 'Runs after launch'),
            skipped(
                'split_changed_mid_run',
                'Variant split changes since launch',
                'not_applicable',
                'Runs after launch'
            ),
            skipped('no_metric', 'Metrics', 'not_applicable', 'Runs after launch'),
        ],
        notes: [
            {
                code: 'new_flag_no_traffic',
                subcode: null,
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
    status: 'finding',
    reason: null,
})

export const DraftWithEventsNotReceived: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            skipped('no_metric', 'Metrics', 'not_applicable', 'Runs after launch'),
            found('metric_event_not_ingested', 'Metric events'),
            found('exposure_criteria_cannot_match', 'Exposure criteria'),
        ],
        notes: [
            {
                code: 'metric_event_not_ingested',
                subcode: null,
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
            passed('no_metric', 'Metrics'),
            found('early_significance', 'Sample size behind significant results'),
        ],
        notes: [
            {
                code: 'early_significance',
                subcode: 'below_detectable_effect',
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
            passed('no_metric', 'Metrics'),
        ],
        notes: [],
        isDraft: false,
        exposureChecksMissing: true,
    },
}
