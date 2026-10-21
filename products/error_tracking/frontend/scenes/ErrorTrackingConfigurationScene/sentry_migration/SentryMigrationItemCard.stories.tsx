import { Meta, StoryObj } from '@storybook/react'

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
    already_in_posthog: false,
}

const LEGACY_BROWSER: SentryMigrationItemApi = {
    id: 'inbound_filter:legacy-browsers:safari:None-16',
    category: 'inbound_filter',
    sentry_setting: 'Errors from legacy browsers',
    sentry_value: 'Safari 15 and older',
    fit: 'partial',
    note: 'Sentry parsed the user agent itself. PostHog uses the browser and version the web SDK reports ($browser and $browser_version).',
    suppression_rule_filters: {
        type: 'AND',
        values: [
            { key: '$browser', type: 'event', operator: 'exact', value: ['Safari', 'Mobile Safari'] },
            { key: '$browser_version', type: 'event', operator: 'lt', value: 16 },
        ],
    } as SentryMigrationItemApi['suppression_rule_filters'],
    rate_limit: null,
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
    already_in_posthog: false,
}

const IP_FILTER: SentryMigrationItemApi = {
    id: 'inbound_filter:blocked-ips',
    category: 'inbound_filter',
    sentry_setting: 'IP address filter',
    sentry_value: '192.0.2.0/24',
    fit: 'unsupported',
    note: "PostHog suppression rules can't filter by IP address range, so you need to set this up another way.",
    suppression_rule_filters: null,
    rate_limit: null,
    already_in_posthog: false,
}

/** A selected rule, a rule already in PostHog, a rate limit, and a setting PostHog can't import. */
export const Variants: Story = {
    render: () => (
        <div className="flex flex-col gap-2 w-160">
            <SentryMigrationItemCard item={ERROR_MESSAGE} selected disabledReason={null} onToggle={() => {}} />
            <SentryMigrationItemCard
                item={LEGACY_BROWSER}
                selected={false}
                disabledReason="This project already has this setting"
                onToggle={() => {}}
            />
            <SentryMigrationItemCard item={RATE_LIMIT} selected={false} disabledReason={null} onToggle={() => {}} />
            <SentryMigrationItemCard
                item={IP_FILTER}
                selected={false}
                disabledReason="PostHog can't import this setting"
                onToggle={() => {}}
            />
        </div>
    ),
}
