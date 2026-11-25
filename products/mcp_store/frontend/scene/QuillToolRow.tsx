import { IconChevronRight, IconLock } from '@posthog/icons'
import { Badge, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import type { MCPServerInstallationToolApi } from '../generated/api.schemas'
import type { ToolApprovalState } from '../mcpStoreLogic'
import { ToolPolicyToggle } from './ToolPolicyToggle'

export function QuillToolRow({
    tool,
    state,
    isRemoved,
    setByTeamAdmin,
    expanded,
    onToggleExpanded,
    onPolicyChange,
    policyDisabledReason,
    disabledStates,
    inputSchema,
}: {
    tool: MCPServerInstallationToolApi
    state: ToolApprovalState
    isRemoved: boolean
    setByTeamAdmin: boolean
    expanded: boolean
    onToggleExpanded: () => void
    onPolicyChange: (state: ToolApprovalState) => void
    policyDisabledReason: string | null | undefined
    disabledStates: Partial<Record<ToolApprovalState, string>>
    inputSchema: string
}): JSX.Element {
    return (
        <div
            className={cn('border-b border-border last:border-b-0', isRemoved && 'opacity-50')}
            data-attr={`mcp-tool-row-${tool.tool_name}`}
        >
            <div className="flex flex-wrap items-center gap-2 pr-3">
                <button
                    type="button"
                    aria-expanded={expanded}
                    className="flex min-w-48 flex-1 items-center gap-3 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={onToggleExpanded}
                >
                    <IconChevronRight
                        className={cn(
                            'shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none',
                            expanded && 'rotate-90'
                        )}
                        aria-hidden
                    />
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="flex flex-wrap items-center gap-2">
                            <Text size="xs" className="m-0 font-mono" render={<span />}>
                                {tool.tool_name}
                            </Text>
                            {isRemoved && <Badge variant="warning">Removed</Badge>}
                        </span>
                        {(tool.display_name || tool.description) && (
                            <Text size="xs" variant="muted" className="m-0 truncate" render={<span />}>
                                {tool.description || tool.display_name}
                            </Text>
                        )}
                    </span>
                </button>
                <div className="flex flex-wrap items-center gap-2">
                    {setByTeamAdmin && (
                        <Tooltip>
                            <TooltipTrigger render={<Badge tabIndex={0} />}>
                                <IconLock />
                                Set by team admin
                            </TooltipTrigger>
                            <TooltipContent>This effective state is capped by the team admin ceiling.</TooltipContent>
                        </Tooltip>
                    )}
                    <ToolPolicyToggle
                        value={state}
                        onChange={onPolicyChange}
                        disabledReason={policyDisabledReason}
                        disabledStates={disabledStates}
                    />
                </div>
            </div>
            {expanded && (
                <div data-quill className="flex flex-col gap-4 bg-muted px-9 py-3">
                    {tool.description && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {tool.description}
                        </Text>
                    )}
                    <div className="flex flex-col gap-1">
                        <Text size="xs" weight="semibold" variant="muted" className="m-0 uppercase" render={<span />}>
                            Input schema
                        </Text>
                        <pre className="m-0 max-h-64 overflow-auto rounded-md bg-background p-2 text-xs">
                            {inputSchema}
                        </pre>
                    </div>
                </div>
            )}
        </div>
    )
}
