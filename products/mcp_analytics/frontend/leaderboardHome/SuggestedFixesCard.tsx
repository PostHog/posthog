import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { Card, CardState } from '../dashboard/Card'
import { ChartSkeleton } from '../dashboard/ChartSkeleton'
import { HarnessLabel } from '../dashboard/HarnessLabel'
import { pickSharedFilterParams } from '../mcpAnalyticsFiltersLogic'
import { MissingCapabilitySessionDrawer } from '../missingCapabilities/MissingCapabilitySessionDrawer'
import { dashboardSuggestedFixesLogic } from './dashboardSuggestedFixesLogic'

export function SuggestedFixesCard(): JSX.Element {
    const { suggestedFixes, suggestedFixesLoading, suggestedFixesFailed, openedFix } =
        useValues(dashboardSuggestedFixesLogic)
    const { loadSuggestedFixes, openFix } = useActions(dashboardSuggestedFixesLogic)
    const { searchParams } = useValues(router)
    const capabilitiesUrl = combineUrl(urls.mcpAnalyticsMissingCapabilities(), pickSharedFilterParams(searchParams)).url
    const listUrl = combineUrl(capabilitiesUrl, { suggested: true }).url

    return (
        <>
            <Card
                title="Suggested fixes"
                description="Changes agents said would have helped when a tool they needed was missing, newest first."
                // The empty state links to the same page, so the header link only shows with rows to see more of.
                action={
                    suggestedFixes.length > 0 ? (
                        <Button
                            variant="link-muted"
                            size="sm"
                            onClick={() => router.actions.push(listUrl)}
                            data-attr="mcp-dashboard-suggested-fixes-view-all"
                        >
                            View all
                        </Button>
                    ) : undefined
                }
                className="min-w-0"
                flush
            >
                <CardState
                    loading={suggestedFixesLoading && suggestedFixes.length === 0}
                    isEmpty={suggestedFixes.length === 0}
                    failed={suggestedFixesFailed}
                    onRetry={loadSuggestedFixes}
                    className="min-h-32"
                    skeleton={<ChartSkeleton kind="bars" />}
                    empty={
                        <Empty className="border-none px-4 py-6">
                            <EmptyHeader>
                                <EmptyTitle>No suggested fixes in this date range</EmptyTitle>
                                <EmptyDescription>
                                    Agents suggest a fix when they report a capability they needed and couldn't find.
                                </EmptyDescription>
                            </EmptyHeader>
                            <EmptyContent>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    render={<LinkPrimitive to={capabilitiesUrl} />}
                                    data-attr="mcp-dashboard-suggested-fixes-empty-link"
                                >
                                    View missing capabilities
                                </Button>
                            </EmptyContent>
                        </Empty>
                    }
                >
                    <Table fullWidth>
                        <TableHeader>
                            <TableRow>
                                <TableHead expand>Suggested fix</TableHead>
                                <TableHead>Harness</TableHead>
                                <TableHead align="right">When</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {suggestedFixes.map((row, index) => (
                                <TableRow
                                    key={`${row.timestamp}-${index}`}
                                    className={cn('cursor-pointer', row === openedFix && 'bg-fill-highlight-100')}
                                    onClick={() => openFix(row)}
                                    data-attr="mcp-dashboard-suggested-fix-row"
                                >
                                    <TableCell expand className="whitespace-normal">
                                        <div className="text-sm">{row.suggested_improvement}</div>
                                        {row.intent ? (
                                            <div className="line-clamp-1 text-xs text-secondary">{row.intent}</div>
                                        ) : null}
                                    </TableCell>
                                    <TableCell>
                                        <HarnessLabel category={row.harness} />
                                    </TableCell>
                                    <TableCell align="right" className="whitespace-nowrap">
                                        <TZLabel time={row.timestamp} />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </CardState>
            </Card>
            <MissingCapabilitySessionDrawer reports={suggestedFixes} openedReport={openedFix} onOpen={openFix} />
        </>
    )
}
