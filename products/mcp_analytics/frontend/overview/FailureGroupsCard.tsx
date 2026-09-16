import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import {
    Card,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'

import type { MCPFailureGroup } from '~/queries/schema/schema-general'

import { formatNumber } from '../dashboard/formatters'
import { CreateFixTaskButton } from '../tool-quality/CreateFixTaskButton'
import type { MCPErrorContext } from '../tool-quality/errorContext'
import { mcpOverviewLogic } from './mcpOverviewLogic'
import { buildAgentNextSegments, buildFailureInvestigationPrompt } from './overviewCopy'
import { ToolTag } from './ToolTag'

function failureContext(group: MCPFailureGroup): MCPErrorContext {
    return {
        toolName: group.tool,
        errorType: group.error_type,
        errorMessage: group.message,
        intent: group.sample_intent || undefined,
    }
}

function AgentNextCell({ group }: { group: MCPFailureGroup }): JSX.Element {
    return (
        <span className="text-muted">
            {buildAgentNextSegments(group).map((segment, index) => (
                <span key={segment.text} className={cn(segment.danger && 'text-danger')}>
                    {index > 0 ? ', ' : ''}
                    {segment.text}
                </span>
            ))}
        </span>
    )
}

function FailureRows(): JSX.Element {
    const { failureGroups, failureGroupsLoading } = useValues(mcpOverviewLogic)

    if (failureGroupsLoading && failureGroups.length === 0) {
        return (
            <TableBody>
                <TableRow>
                    <TableCell colSpan={4}>
                        <div className="space-y-2 py-1">
                            {Array.from({ length: 4 }).map((_, index) => (
                                <LemonSkeleton key={index} className="h-3.5 w-full" />
                            ))}
                        </div>
                    </TableCell>
                </TableRow>
            </TableBody>
        )
    }
    if (failureGroups.length === 0) {
        return <TableEmpty className="py-6 text-secondary">Nothing failed in this range.</TableEmpty>
    }
    return (
        <TableBody>
            {failureGroups.map((group) => (
                <TableRow key={`${group.tool}-${group.error_type}-${group.message}`}>
                    <TableCell expand>
                        <div className="flex min-w-0 flex-col gap-1">
                            <span className="flex flex-wrap items-center gap-1.5">
                                <ToolTag name={group.tool} />
                                <span className="min-w-0 break-words">{group.message}</span>
                            </span>
                            {group.sample_intent && (
                                <span className="text-muted" title={group.sample_intent}>
                                    While: {group.sample_intent}
                                </span>
                            )}
                        </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap" translate="no">
                        <span className="font-semibold">{formatNumber(group.sessions)}</span>
                        <span className="text-muted"> · {formatNumber(group.calls)} calls</span>
                    </TableCell>
                    <TableCell>
                        <AgentNextCell group={group} />
                    </TableCell>
                    <TableCell align="right" className="whitespace-nowrap">
                        <CreateFixTaskButton context={failureContext(group)} />
                    </TableCell>
                </TableRow>
            ))}
        </TableBody>
    )
}

/** Failures ranked by how many sessions ran into them, not by how often they fire. */
export function FailureGroupsCard(): JSX.Element {
    const { failureGroups } = useValues(mcpOverviewLogic)
    const { askPostHogAI } = useActions(mcpOverviewLogic)
    const topGroup = failureGroups[0]

    return (
        <Card size="sm" className="gap-0">
            <CardHeader className="flex-row items-center justify-between gap-2 border-b border-border pb-3">
                <CardTitle>What is failing, by people affected</CardTitle>
                <span className="text-xs text-muted">Grouped by error message, not by rate</span>
            </CardHeader>
            <CardContent className="p-0">
                <Table fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>What broke</TableHead>
                            <TableHead>Sessions hit</TableHead>
                            <TableHead>What the agent did next</TableHead>
                            <TableHead align="right" />
                        </TableRow>
                    </TableHeader>
                    <FailureRows />
                </Table>
            </CardContent>
            <CardFooter className="flex-wrap items-center justify-between gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconSparkles />}
                    disabledReason={topGroup ? undefined : 'No failures to investigate'}
                    onClick={() => topGroup && askPostHogAI(buildFailureInvestigationPrompt(topGroup), 'failures')}
                    data-attr="mcp-overview-investigate-failures"
                >
                    Investigate with PostHog AI
                </LemonButton>
                <span className="text-xs text-muted">
                    Opens PostHog AI with the top failure, its message and the intent behind it already in context.
                </span>
            </CardFooter>
        </Card>
    )
}
