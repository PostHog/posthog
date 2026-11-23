import { IconCheck, IconRefresh, IconShieldLock, IconX } from '@posthog/icons'
import { Badge, Button, Empty, EmptyDescription, EmptyHeader, Heading, Skeleton, Text } from '@posthog/quill'

import type { MCPServerInstallationToolApi } from '../generated/api.schemas'
import type { ToolApprovalState } from '../mcpStoreLogic'
import { ToolRow } from './ToolRow'

export function QuillToolsSection({
    tools,
    visibleTools,
    teamScope,
    loading,
    disabledReason,
    approvedCount,
    pendingCount,
    blockedCount,
    removedCount,
    showRemoved,
    onToggleShowRemoved,
    onRefresh,
    onSetAll,
    onPolicyChange,
}: {
    tools: MCPServerInstallationToolApi[]
    visibleTools: MCPServerInstallationToolApi[]
    teamScope: boolean
    loading: boolean
    disabledReason: string | null
    approvedCount: number
    pendingCount: number
    blockedCount: number
    removedCount: number
    showRemoved: boolean
    onToggleShowRemoved: () => void
    onRefresh: () => void
    onSetAll: (approvalState: ToolApprovalState) => void
    onPolicyChange: (toolName: string, state: ToolApprovalState) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Tools
                    </Heading>
                    <Badge>{tools.length}</Badge>
                </div>
                <Button variant="outline" onClick={onRefresh} loading={loading} disabledReason={disabledReason}>
                    <IconRefresh />
                    Refresh tools
                </Button>
            </div>

            {tools.length > 0 && (
                <div data-quill className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted p-2">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        <span className="font-semibold">{approvedCount}</span> Always Allow ·{' '}
                        <span className="font-semibold">{pendingCount}</span> Needs Approval ·{' '}
                        <span className="font-semibold">{blockedCount}</span> Blocked
                    </Text>
                    <div className="flex flex-wrap items-center gap-1">
                        <Text size="xs" variant="muted" className="m-0" render={<span />}>
                            Set all:
                        </Text>
                        <Button variant="outline" onClick={() => onSetAll('approved')} disabledReason={disabledReason}>
                            <IconCheck />
                            Always Allow
                        </Button>
                        <Button
                            variant="outline"
                            onClick={() => onSetAll('needs_approval')}
                            disabledReason={disabledReason}
                        >
                            <IconShieldLock />
                            Needs Approval
                        </Button>
                        <Button
                            variant="destructive-outline"
                            onClick={() => onSetAll('do_not_use')}
                            disabledReason={disabledReason}
                        >
                            <IconX />
                            Block
                        </Button>
                    </div>
                </div>
            )}

            {removedCount > 0 && (
                <div>
                    <Button onClick={onToggleShowRemoved}>
                        {showRemoved ? `Hide ${removedCount} removed` : `Show ${removedCount} removed`}
                    </Button>
                </div>
            )}

            {visibleTools.length === 0 ? (
                loading ? (
                    <div className="flex flex-col gap-2">
                        <Skeleton className="h-10 w-full" />
                        <Skeleton className="h-10 w-full" />
                    </div>
                ) : (
                    <Empty className="rounded-md border border-dashed border-border">
                        <EmptyHeader>
                            <EmptyDescription>
                                No tools reported yet. Click "Refresh tools" after connecting.
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                )
            ) : (
                <div className="overflow-hidden rounded-md border border-border">
                    {visibleTools.map((tool) => (
                        <ToolRow
                            key={tool.id}
                            tool={tool}
                            teamScope={teamScope}
                            disabledReason={disabledReason}
                            onPolicyChange={(state: ToolApprovalState) => onPolicyChange(tool.tool_name, state)}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
