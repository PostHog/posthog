import { Meta, StoryObj } from '@storybook/react'

import { CardGroup, TooltipProvider } from '@posthog/quill'

import type { SentryMigrationItemApi } from '../../../generated/api.schemas'
import { SentryMigrationItemCard } from './SentryMigrationItemCard'

const meta: Meta<typeof SentryMigrationItemCard> = {
    title: 'ErrorTracking/SentryMigrationItemCard',
    component: SentryMigrationItemCard,
    parameters: {
        layout: 'padded',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof SentryMigrationItemCard>

const ERROR_MESSAGE: SentryMigrationItemApi = {
    id: 'error_message:1',
    category: 'error_message',
    sentry_setting: 'Error message filter',
    sentry_value: 'TypeError: Failed to fetch*',
    fit: 'good',
    note: null,
    suppression_rule_filters: {
        type: 'AND',
        values: [
            { key: '$exception_types', type: 'event', operator: 'exact', value: ['TypeError'] },
            { key: '$exception_values', type: 'event', operator: 'regex', value: '(?is)^Failed to fetch.*$' },
        ],
    } as SentryMigrationItemApi['suppression_rule_filters'],
    rate_limit: null,
    built_in_filter: null,
    already_in_posthog: false,
}

const LEGACY_BROWSER: SentryMigrationItemApi = {
    id: 'inbound_filter:legacy-browsers',
    category: 'inbound_filter',
    sentry_setting: 'Errors from legacy browsers',
    sentry_value: 'Internet Explorer 11, Safari 5 and older',
    fit: 'partial',
    note: null,
    suppression_rule_filters: null,
    rate_limit: null,
    built_in_filter: {
        key: 'legacy_browsers',
        name: 'Legacy browsers',
        description:
            'Drop exceptions from Internet Explorer, Chrome before 87, Edge before 88, Firefox before 78, Safari before 14 and Opera before 73.',
        compared_with_sentry: [
            'Replaces your Sentry selection (Internet Explorer 11, Safari 5 and older) with these versions',
        ],
    },
    already_in_posthog: true,
}

const RATE_LIMIT: SentryMigrationItemApi = {
    id: 'rate_limit:key',
    category: 'rate_limit',
    sentry_setting: 'Rate limit on client key "Default"',
    sentry_value: '100 events per 1 minute',
    fit: 'partial',
    note: 'PostHog rate limits use 15, 30 or 60 minute windows, so this becomes 1,500 exceptions per 15 minutes.',
    suppression_rule_filters: null,
    rate_limit: { value: 1500, bucket_size_minutes: 15 },
    built_in_filter: null,
    already_in_posthog: false,
}

const RATE_LIMIT_TOO_LARGE: SentryMigrationItemApi = {
    id: 'rate_limit:big',
    category: 'rate_limit',
    sentry_setting: 'Rate limit on client key "Backend"',
    sentry_value: '3,000,000 events per 1 second',
    fit: 'unsupported',
    note: 'This becomes 2,700,000,000 exceptions per 15 minutes, which is more than a PostHog rate limit can hold.',
    suppression_rule_filters: null,
    rate_limit: null,
    built_in_filter: null,
    already_in_posthog: false,
}

/** A manual rule, an automatic rule that is already on, a rate limit, and a rate limit PostHog can't hold. */
export const Variants: Story = {
    render: () => (
        <TooltipProvider>
            <CardGroup size="sm" className="w-160">
                <SentryMigrationItemCard item={ERROR_MESSAGE} selected disabledReason={null} onToggle={() => {}} />
                <SentryMigrationItemCard
                    item={LEGACY_BROWSER}
                    selected={false}
                    disabledReason="This automatic suppression rule is already on"
                    onToggle={() => {}}
                />
                <SentryMigrationItemCard item={RATE_LIMIT} selected disabledReason={null} onToggle={() => {}} />
                <SentryMigrationItemCard
                    item={RATE_LIMIT_TOO_LARGE}
                    selected={false}
                    disabledReason="PostHog can't import this setting"
                    onToggle={() => {}}
                />
            </CardGroup>
        </TooltipProvider>
    ),
}
