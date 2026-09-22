import { DiscoveryScatter } from './DiscoveryScatter'
import { ToolOverlapTable } from './ToolOverlapTable'
import { ToolPivotTable } from './ToolPivotTable'

/**
 * The whole-snapshot side of the tools view: every tool, then the two charts that only
 * mean anything across all of them. Scrolls as one column beside the selected tool's
 * detail, so the population and the pick stay on screen together.
 */
export function ToolsListPanel(): JSX.Element {
    return (
        // Scrolls both ways so the pane can be narrowed past the tool table's natural
        // width instead of the table dictating how much room the detail gets.
        <div className="flex h-full min-h-0 flex-col overflow-auto gap-4 pr-1">
            <ToolPivotTable />
            <DiscoveryScatter />
            <ToolOverlapTable />
        </div>
    )
}
