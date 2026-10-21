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
