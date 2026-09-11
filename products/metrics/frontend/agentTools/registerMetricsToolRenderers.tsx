import { IconGraph, IconList, IconWarning } from '@posthog/icons'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { registerToolRenderers } from 'products/posthog_ai/frontend/api/tools'

// The card pulls its chunk on first use, so registering the whole family stays a strings-and-icons cost.
const MetricsQueryRenderer = lazyWithRetry(() =>
    import('./MetricsQueryToolWidget').then((m) => ({ default: m.MetricsQueryToolWidget }))
)

/**
 * Claim the metrics tool names in the shared registry. Called from `bootApp` rather than run at
 * module load: a thread renders tool cards wherever it is opened, including an `/ai/{id}` link
 * followed before the lazy Metrics scene has ever loaded, so registering from the scene entrypoint
 * would leave those calls on the generic wrench card. `requiresPostHogOrigin` so a user-installed
 * MCP tool with a colliding bare name does not borrow the metrics branding.
 */
export function registerMetricsToolRenderers(): void {
    registerToolRenderers([
        // The flagship: charts the returned series as sparklines.
        {
            key: 'query-metrics',
            displayName: 'Query metrics',
            icon: <IconGraph />,
            Renderer: MetricsQueryRenderer,
            requiresPostHogOrigin: true,
        },
        {
            key: 'metric-names-list',
            displayName: 'List metrics',
            icon: <IconList />,
            requiresPostHogOrigin: true,
        },
        {
            key: 'characterize-metric-anomaly',
            displayName: 'Characterize metric anomaly',
            icon: <IconWarning />,
            requiresPostHogOrigin: true,
        },
    ])
}
