import { useValues } from 'kea'

import { IconLock } from '@posthog/icons'

import { organizationLogic } from 'scenes/organizationLogic'

import { DataToolRow } from '../DataToolRow'
import { GenericMcpToolRenderer } from '../GenericMcpToolRenderer'
import type { ToolRendererProps } from '../toolRegistry'
import { extractQueryResult } from './extractors'
import { VisualizationWidget, getQueryOpenTarget } from './VisualizationWidget'

/**
 * Renders the MCP query-wrapper tools (query-trends, query-funnel, ...) through
 * `VisualizationWidget` as inline ephemeral visualizations. Pending calls and outputs without an
 * inline renderer fall back to the generic card.
 */
export function QueryWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const { currentOrganization } = useValues(organizationLogic)
    const result = message.status === 'completed' ? extractQueryResult(message) : null

    if (!result) {
        return <GenericMcpToolRenderer {...props} />
    }

    // Not every wrapper output carries the MCP server's `_posthogUrl` enrichment — fall back to
    // opening the rendered query as a new unsaved insight, like the artifact path does.
    const target = result.url ? { url: result.url, tooltip: 'Open as insight' } : getQueryOpenTarget(result.content)

    return (
        <DataToolRow {...props}>
            <VisualizationWidget
                content={result.content}
                openUrl={target.url}
                openTooltip={target.tooltip}
                footerNote={
                    currentOrganization?.ai_data_access === 'metadata_only' ? (
                        <div
                            className="flex items-center gap-1 text-xs text-muted"
                            data-attr="query-widget-data-access-note"
                        >
                            <IconLock className="shrink-0" />
                            Only you can see this chart. PostHog AI didn't see its data.
                        </div>
                    ) : null
                }
            />
        </DataToolRow>
    )
}
