import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { MCPServerInstallationToolApi } from '../generated/api.schemas'
import type { ToolApprovalState } from '../mcpStoreLogic'
import { ToolPolicyToggle } from './ToolPolicyToggle'

interface Props {
    tool: MCPServerInstallationToolApi
    onPolicyChange: (state: ToolApprovalState) => void
    disabledReason?: string | null
}

function formatInputSchema(schema: unknown): string {
    try {
        return JSON.stringify(schema ?? {}, null, 2)
    } catch {
        return String(schema)
    }
}

export function ToolRow({ tool, onPolicyChange, disabledReason }: Props): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const state = (tool.approval_state ?? 'needs_approval') as ToolApprovalState
    const isRemoved = !!tool.removed_at

    return (
        <div
            className={`border-b last:border-b-0 border-primary ${isRemoved ? 'opacity-50' : ''}`}
            data-attr={`mcp-tool-row-${tool.tool_name}`}
        >
            <div
                className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-surface-secondary transition-colors"
                onClick={() => setExpanded((v) => !v)}
                role="button"
            >
                <IconChevronRight className={`text-secondary transition-transform ${expanded ? 'rotate-90' : ''}`} />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="font-mono text-sm">{tool.tool_name}</span>
                        {isRemoved && (
                            <LemonTag type="warning" size="small">
                                Removed
                            </LemonTag>
                        )}
                    </div>
                    {(tool.display_name || tool.description) && (
                        <div className="text-xs text-secondary truncate">{tool.description || tool.display_name}</div>
                    )}
                </div>
                {/* Clicks on the toggle shouldn't collapse the row. */}
                <div onClick={(e) => e.stopPropagation()}>
                    <ToolPolicyToggle value={state} onChange={onPolicyChange} disabledReason={disabledReason} />
                </div>
            </div>
            {expanded && (
                <div className="px-9 py-3 deprecated-space-y-4 bg-surface-secondary">
                    {tool.description && <div className="text-sm text-secondary">{tool.description}</div>}
                    <div>
                        <div className="text-xs font-semibold uppercase text-secondary mb-1">Input schema</div>
                        <pre className="text-xs bg-surface-secondary rounded p-2 overflow-auto max-h-64">
                            {formatInputSchema(tool.input_schema)}
                        </pre>
                    </div>
                </div>
            )}
        </div>
    )
}
