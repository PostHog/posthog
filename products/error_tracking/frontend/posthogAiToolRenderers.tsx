import { IconWarning } from '@posthog/icons'

import { lazyWithRetry } from 'lib/utils/retryImport'

import type { ToolRegistryEntry } from 'products/posthog_ai/frontend/api/tools'

const ErrorTrackingRenderer = lazyWithRetry(() =>
    import('./posthogAi/ErrorTrackingWidget').then((m) => ({ default: m.ErrorTrackingWidget }))
)

export const posthogAiToolRenderers: ToolRegistryEntry[] = [
    'query-error-tracking-issues-list',
    'query-error-tracking-issue',
    'query-error-tracking-issue-events',
].map((key) => ({
    key,
    displayName: 'Error tracking',
    icon: <IconWarning />,
    Renderer: ErrorTrackingRenderer,
    requiresPostHogOrigin: true,
    keepVisible: true,
}))
