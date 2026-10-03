import { useValues } from 'kea'

import { mcpClusteringLogic } from './mcpClusteringLogic'
import { ToolIntentDetail } from './ToolIntentDetail'

/** The selected tool's intents and competitors, pinned beside the tool list. */
export function ToolDetailPanel(): JSX.Element {
    const { selectedTool, clusters, categoriesByTool } = useValues(mcpClusteringLogic)

    if (!selectedTool) {
        return (
            <div className="flex h-full items-center justify-center rounded border border-primary bg-surface-primary p-6 text-center text-sm text-muted">
                Pick a tool to see the intents it serves and who it competes with.
            </div>
        )
    }

    return (
        // Scrolls both ways: the intents table carries a competitor column that a narrow
        // pane can't fit, and clipping it silently would hide the comparison it exists for.
        <div className="h-full min-h-0 overflow-auto">
            <ToolIntentDetail
                tool={selectedTool}
                clusters={clusters}
                categories={categoriesByTool[selectedTool.tool] ?? []}
            />
        </div>
    )
}
