import { BindLogic } from 'kea'

import { MCPDetailDrawer, type MCPDetailDrawerPosition } from '../components/MCPDetailDrawer'
import { mcpAnalyticsToolDetailLogic } from '../mcpAnalyticsToolDetailLogic'
import { MCPToolReport } from '../MCPToolReport'

export function ToolReportDrawer({
    tool,
    position,
    previousTool,
    nextTool,
    onOpen,
    fullPageHref,
    dataAttr,
}: {
    tool: string | null
    position: MCPDetailDrawerPosition | null
    previousTool: string | null
    nextTool: string | null
    /** null closes. */
    onOpen: (tool: string | null) => void
    fullPageHref: string
    dataAttr: string
}): JSX.Element | null {
    if (!tool) {
        return null
    }
    return (
        <MCPDetailDrawer
            noun="tool"
            title={<span className="font-mono">{tool}</span>}
            position={position}
            onPrevious={previousTool ? () => onOpen(previousTool) : null}
            onNext={nextTool ? () => onOpen(nextTool) : null}
            fullPageHref={fullPageHref}
            onClose={() => onOpen(null)}
            data-attr={dataAttr}
        >
            <BindLogic logic={mcpAnalyticsToolDetailLogic} props={{ toolName: tool }}>
                <MCPToolReport />
            </BindLogic>
        </MCPDetailDrawer>
    )
}
