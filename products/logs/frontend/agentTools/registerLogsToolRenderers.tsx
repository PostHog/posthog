import { IconBell, IconList, IconPulse, IconSearch, IconServer, IconStack, IconWarning } from '@posthog/icons'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { registerToolRenderers, type ToolRegistryEntry } from 'products/posthog_ai/frontend/api/tools'

// The card pulls its chunk on first use, so registering the whole family stays a strings-and-icons cost.
const LogsQueryRenderer = lazyWithRetry(() =>
    import('./LogsQueryToolWidget').then((m) => ({ default: m.LogsQueryToolWidget }))
)

// Friendly header (name + icon) for a logs tool call, without a bespoke result card. A no-Renderer
// entry keeps its displayName and icon on the generic card (see `lookupToolRenderer`), so the whole
// logs tool family reads as intentional logs actions in a thread even where only query-logs draws a
// custom card. `requiresPostHogOrigin` so a user-installed MCP tool with a colliding bare name does
// not borrow the logs branding.
function labelled(keys: string[], displayName: string, icon: JSX.Element): ToolRegistryEntry[] {
    return keys.map((key) => ({ key, displayName, icon, requiresPostHogOrigin: true }))
}

/**
 * Claim the logs tool names in the shared registry. Called from `bootApp` rather than run at module
 * load: a thread renders tool cards wherever it is opened, including an `/ai/{id}` link followed
 * before the lazy Logs scene has ever loaded, so registering from the scene entrypoint would leave
 * those calls on the generic wrench card.
 */
export function registerLogsToolRenderers(): void {
    registerToolRenderers([
        // The flagship: renders the returned log rows as a compact severity-tagged list.
        {
            key: 'query-logs',
            displayName: 'Query logs',
            icon: <IconSearch />,
            Renderer: LogsQueryRenderer,
            requiresPostHogOrigin: true,
        },
        ...labelled(['logs-services-create'], 'Logs services', <IconServer />),
        ...labelled(['logs-patterns', 'logs-patterns-diff'], 'Log patterns', <IconStack />),
        ...labelled(['logs-count', 'logs-count-ranges', 'logs-sparkline-query'], 'Count logs', <IconPulse />),
        ...labelled(
            ['logs-attributes-list', 'logs-attribute-values-list', 'logs-facet-values-create'],
            'Log attributes',
            <IconList />
        ),
        ...labelled(['logs-anomalies-scan', 'logs-anomalies-series-bands'], 'Log anomalies', <IconWarning />),
        ...labelled(
            [
                'logs-alerts-list',
                'logs-alerts-retrieve',
                'logs-alerts-create',
                'logs-alerts-partial-update',
                'logs-alerts-destroy',
                'logs-alerts-simulate-create',
                'logs-alerts-events-list',
                'logs-alerts-destinations-create',
                'logs-alerts-destinations-delete-create',
            ],
            'Log alert',
            <IconBell />
        ),
    ])
}
