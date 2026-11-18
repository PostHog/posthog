import * as greekPng from '@posthog/brand/hoggies/png/greek'
import { IconLive } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { LogsPreview } from './LogsPreview'
import { logsSetupLogic } from './logsSetupLogic'

const HedgehogGreek = pngHoggie(greekPng)

export const logsEmptyState: SceneProductEmptyState = {
    statusLogic: logsSetupLogic,
    config: {
        productKey: ProductKey.LOGS,
        productName: 'Logs',
        icon: <IconLive />,
        accentColor: 'var(--color-product-logs-light)',
        accentColorDark: 'var(--color-product-logs-dark)',
        hedgehog: HedgehogGreek,
        text: {
            'needs-setup': {
                headline: 'Search every log from your stack in one place',
                lead: 'Send logs from any OpenTelemetry-compatible client over OTLP. No PostHog-specific packages needed. Filter by severity and attributes, query with SQL, and set alerts on the lines that matter.',
            },
        },
        docsUrl: 'https://posthog.com/docs/logs',
        manualSetupUrl: 'https://posthog.com/docs/logs/installation',
        previewLabel: 'Your log stream, once connected',
        Preview: LogsPreview,
    },
}
