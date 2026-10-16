import { useActions } from 'kea'

import { IconChevronRight } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    Button,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import { ImpactFindingReach } from './ImpactFindingReach'
import { ImpactFindingReachLine } from './ImpactFindingReachLine'
import type { ImpactFinding } from './impactFindings'
import { ImpactFindingSignal } from './ImpactFindingSignal'
import { relatedPairTitle } from './impactFormat'
import { IMPACT_LENS_INFO } from './impactLenses'
import { ImpactMergeAction } from './ImpactMergeAction'
import { impactTabLogic } from './impactTabLogic'

const findingKey = (finding: ImpactFinding): string =>
    finding.lens === 'related_issues'
        ? `${finding.lens}-${finding.issue.id}-${finding.issue.related.id}`
        : `${finding.lens}-${finding.issue.id}`

const findingTitle = (finding: ImpactFinding): string =>
    finding.lens === 'related_issues'
        ? relatedPairTitle(finding.issue)
        : finding.issue.description || finding.issue.name

// One row per finding. With several lenses in one list, each row names the lens that flagged it. Below the container
// breakpoint the reach column moves under the title and the signal column narrows, so the table fits a narrow scene
// next to the navigation and a side panel.
export function ImpactIssueList({ findings, showLens }: { findings: ImpactFinding[]; showLens: boolean }): JSX.Element {
    const { reportIssueClicked } = useActions(impactTabLogic)

    return (
        <Table size="sm" fullWidth>
            <TableHeader>
                <TableRow>
                    <TableHead expand>Issue</TableHead>
                    <TableHead>Signal</TableHead>
                    <TableHead className="hidden @min-[44rem]/impact:table-cell">Reach</TableHead>
                    <TableHead>
                        <span className="sr-only">Open</span>
                    </TableHead>
                </TableRow>
            </TableHeader>

            <TableBody>
                {findings.map((finding) => {
                    const issueUrl = urls.errorTrackingIssue(finding.issue.id)
                    return (
                        <TableRow key={findingKey(finding)}>
                            <TableCell expand valign="top">
                                <div className="flex min-w-32 flex-col gap-0.5 py-1">
                                    {finding.issue.description && (
                                        <Text size="xs" variant="muted" className="truncate">
                                            {finding.issue.name}
                                        </Text>
                                    )}
                                    <LinkPrimitive
                                        to={issueUrl}
                                        onClick={() => reportIssueClicked(finding.lens, finding.issue.id)}
                                        className="line-clamp-2 text-sm font-semibold text-foreground hover:underline"
                                        data-attr="error-tracking-impact-issue"
                                    >
                                        {findingTitle(finding)}
                                    </LinkPrimitive>
                                    {showLens && (
                                        <Text render={<span />} size="xs" variant="muted">
                                            {IMPACT_LENS_INFO[finding.lens].label}
                                        </Text>
                                    )}
                                    <div className="@min-[44rem]/impact:hidden">
                                        <ImpactFindingReachLine finding={finding} />
                                    </div>
                                </div>
                            </TableCell>
                            <TableCell valign="top">
                                <div className="w-44 py-1 @min-[44rem]/impact:w-64">
                                    <ImpactFindingSignal finding={finding} />
                                </div>
                            </TableCell>
                            <TableCell valign="top" className="hidden @min-[44rem]/impact:table-cell">
                                <div className="w-32 py-1">
                                    <ImpactFindingReach finding={finding} />
                                </div>
                            </TableCell>
                            <TableCell valign="middle" align="right">
                                <div className="flex items-center justify-end gap-1">
                                    {finding.lens === 'related_issues' && finding.issue.relation === 'same' && (
                                        <ImpactMergeAction pair={finding.issue} />
                                    )}
                                    <Tooltip>
                                        <TooltipTrigger
                                            delay={0}
                                            render={
                                                <Button
                                                    size="icon-sm"
                                                    nativeButton={false}
                                                    aria-label="Open issue"
                                                    render={
                                                        <LinkPrimitive
                                                            to={issueUrl}
                                                            onClick={() =>
                                                                reportIssueClicked(finding.lens, finding.issue.id)
                                                            }
                                                        />
                                                    }
                                                />
                                            }
                                        >
                                            <IconChevronRight />
                                        </TooltipTrigger>
                                        <TooltipContent>Open issue</TooltipContent>
                                    </Tooltip>
                                </div>
                            </TableCell>
                        </TableRow>
                    )
                })}
            </TableBody>
        </Table>
    )
}
