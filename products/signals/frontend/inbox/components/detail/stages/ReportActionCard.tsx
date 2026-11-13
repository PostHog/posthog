import { useState } from 'react'

import { IconChevronDown, IconExternal, IconPullRequest } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Item,
    ItemActions,
    ItemContent,
    ItemFooter,
    ItemMedia,
    ItemTitle,
    Text,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SignalReport, SignalReportArtefact } from '../../../types'
import { displayConventionalCommitTitle, parsePrUrlParts, safeHttpUrl } from '../../../utils/reportPresentation'
import { primaryReportPullRequest, ReportPullRequest, reportPullRequests } from '../../../utils/reportPullRequests'
import { parseReportSummary } from '../../../utils/reportSummary'
import { CommitContent } from '../artefactTypes'
import { IMPLEMENTATION_AGENTS, ImplementationAgent } from '../implementationAgents'
import { ReportStageProse } from './ReportStageProse'

type BadgeVariant = 'default' | 'info' | 'success' | 'completed' | 'destructive'

/** The agents listed first in the "Send to" menu. The rest sit one step away, under "More". */
const TOP_AGENT_COUNT = 5

function workState(
    report: SignalReport,
    pullRequest: ReportPullRequest | null
): { label: string; variant: BadgeVariant } {
    if (!pullRequest) {
        return report.implementation_in_flight || report.assignee
            ? { label: 'In progress', variant: 'info' }
            : { label: 'Ready to start', variant: 'default' }
    }
    if (pullRequest.state === 'merged') {
        return { label: 'Merged', variant: 'completed' }
    }
    if (pullRequest.state === 'closed') {
        return { label: 'Closed', variant: 'destructive' }
    }
    if (pullRequest.state === 'draft') {
        return { label: 'Draft', variant: 'default' }
    }
    return pullRequest.review_decision === 'approved'
        ? { label: 'Approved', variant: 'success' }
        : { label: 'In review', variant: 'info' }
}

/**
 * The one piece of work a report proposes: what to change, where, and how far it has come. Before any
 * work it offers to hand the change to an agent of the reader's choice; after that it follows the pull request.
 */
export function ReportActionCard({
    report,
    artefacts,
    onSendTo,
}: {
    report: SignalReport
    artefacts: SignalReportArtefact[]
    onSendTo: (agent: ImplementationAgent) => void
}): JSX.Element {
    const [detailsOpen, setDetailsOpen] = useState(false)
    const pullRequest = reportPullRequests(report).length > 0 ? primaryReportPullRequest(report) : null
    const pullRequestUrl = safeHttpUrl(pullRequest?.url)
    const pullRequestParts = pullRequestUrl ? parsePrUrlParts(pullRequestUrl) : null
    const commits = artefacts
        .filter((artefact) => artefact.type === 'commit')
        .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))
    const firstCommit = commits.length > 0 ? (commits[0].content as CommitContent) : null
    const solution =
        parseReportSummary(report.summary).sections.find((section) => section.kind === 'solution')?.body ?? null
    const state = workState(report, pullRequest)
    const repository = pullRequestParts?.repoSlug.toLowerCase() ?? report.repo_slug
    // A commit subject starts in lower case by convention, and this line is a heading.
    const title = displayConventionalCommitTitle(firstCommit?.message ?? report.title, 'Untitled report')

    return (
        <Item variant="outline" className="items-start" data-attr="inbox-report-action-card">
            <ItemMedia variant="icon">
                <IconPullRequest />
            </ItemMedia>
            <ItemContent className="min-w-0 gap-1.5">
                <Text size="xs" variant="muted" render={<div />} className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">Coding agent</span>
                    <Badge variant={state.variant}>{state.label}</Badge>
                </Text>
                <ItemTitle className="text-sm">{title.charAt(0).toUpperCase() + title.slice(1)}</ItemTitle>
                {solution && <ReportStageProse markdown={solution} tone="muted" size="xs" />}
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                    {repository && (
                        <Badge variant="default" className="font-mono">
                            {repository}
                        </Badge>
                    )}
                    {pullRequestParts && (
                        <Badge variant="default" className="font-mono">{`#${pullRequestParts.number}`}</Badge>
                    )}
                    {firstCommit?.branch && (
                        <Badge variant="default" className="max-w-full truncate font-mono">
                            {firstCommit.branch}
                        </Badge>
                    )}
                </div>
            </ItemContent>
            <ItemActions className="self-start">
                {pullRequestUrl ? (
                    <Button
                        variant="outline"
                        render={<LinkPrimitive to={pullRequestUrl} target="_blank" />}
                        data-attr="inbox-report-action-open-pr"
                    >
                        Open pull request
                        <IconExternal />
                    </Button>
                ) : (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={<Button variant="outline" data-attr="inbox-report-action-send-to" />}
                        >
                            Send to
                            <IconChevronDown />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            {IMPLEMENTATION_AGENTS.slice(0, TOP_AGENT_COUNT).map((agent) => (
                                <DropdownMenuItem key={agent.key} onClick={() => onSendTo(agent)}>
                                    {agent.icon}
                                    {agent.name}
                                </DropdownMenuItem>
                            ))}
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger>More</DropdownMenuSubTrigger>
                                <DropdownMenuSubContent>
                                    {IMPLEMENTATION_AGENTS.slice(TOP_AGENT_COUNT).map((agent) => (
                                        <DropdownMenuItem key={agent.key} onClick={() => onSendTo(agent)}>
                                            {agent.icon}
                                            {agent.name}
                                        </DropdownMenuItem>
                                    ))}
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </ItemActions>
            {commits.length > 0 && (
                <ItemFooter className="justify-end border-t border-border pt-2">
                    <Button
                        variant="link-muted"
                        size="sm"
                        aria-expanded={detailsOpen}
                        onClick={() => setDetailsOpen(!detailsOpen)}
                        data-attr="inbox-report-action-details"
                    >
                        {detailsOpen ? 'Hide details' : 'Show details'}
                        <IconChevronDown
                            className={cn('transition-transform duration-200', detailsOpen && 'rotate-180')}
                        />
                    </Button>
                </ItemFooter>
            )}
            {detailsOpen && (
                <ul className="m-0 flex basis-full list-none flex-col gap-1.5 p-0">
                    {commits.map((commit) => {
                        const content = commit.content as CommitContent
                        return (
                            <li key={commit.id} className="flex items-baseline gap-2">
                                <Text size="xs" variant="muted" render={<span />} className="shrink-0 font-mono">
                                    {content.commit_sha.slice(0, 7)}
                                </Text>
                                <Text size="xs" render={<span />} className="min-w-0 flex-1 truncate font-mono">
                                    {content.message}
                                </Text>
                                <Text size="xs" variant="muted" render={<span />} className="shrink-0">
                                    <TZLabel time={commit.created_at} />
                                </Text>
                            </li>
                        )
                    })}
                </ul>
            )}
        </Item>
    )
}
