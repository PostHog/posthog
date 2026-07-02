import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPullRequest, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { SignalReportActionabilityBadge } from 'scenes/inbox/components/badges/SignalReportActionabilityBadge'
import { SignalReportPriorityBadge } from 'scenes/inbox/components/badges/SignalReportPriorityBadge'
import { captureInboxReportAction } from 'scenes/inbox/inboxAnalytics'
import { inboxTaskKickoffLogic } from 'scenes/inbox/inboxTaskKickoffLogic'
import { deriveHeadline, displayConventionalCommitTitle, safeHttpUrl } from 'scenes/inbox/utils/reportPresentation'
import { urls } from 'scenes/urls'

import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { IssueFinding, issueAnalysisLogic } from './issueAnalysisLogic'

const MAX_CODE_PATHS = 6
const MAX_COMMITS = 3

/**
 * The signals pipeline researches every new error tracking issue and writes its conclusions to a
 * signal report (summary, suspect code paths and commits, priority, actionability). This card
 * surfaces that report on the issue itself, with the fix CTA the inbox offers.
 */
export function IssueAnalysis(): JSX.Element | null {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const logic = issueAnalysisLogic({ issueId })
    const { report, showCard, researchPending, cta, issueFindings } = useValues(logic)
    const { isCreatingPr } = useValues(inboxTaskKickoffLogic)
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const [summaryExpanded, setSummaryExpanded] = useState(false)

    if (!report || !showCard) {
        return null
    }

    const title = displayConventionalCommitTitle(report.title, 'Issue analysis')
    const headline = deriveHeadline(report.summary)
    const summary = report.summary?.trim()
    const prUrl = safeHttpUrl(report.implementation_pr_url)

    return (
        <div className="flex flex-col gap-1.5 border-b px-3 py-2 shrink-0" data-attr="error-tracking-issue-analysis">
            <div className="flex items-center gap-1.5">
                <IconSparkles className="text-accent shrink-0" />
                <span className="text-xs font-semibold uppercase tracking-wide text-secondary">AI analysis</span>
                <SignalReportPriorityBadge priority={report.priority} />
                <SignalReportActionabilityBadge actionability={report.actionability} />
                {researchPending && (
                    <span className="flex items-center gap-1 text-xs text-tertiary">
                        <Spinner className="text-sm" />
                        Analyzing…
                    </span>
                )}
            </div>

            {report.title && <div className="text-sm font-semibold break-words">{title}</div>}

            {summary &&
                (summaryExpanded ? (
                    <LemonMarkdown className="text-xs" lowKeyHeadings>
                        {summary}
                    </LemonMarkdown>
                ) : (
                    headline && <p className="m-0 text-xs text-secondary break-words">{headline}</p>
                ))}
            {summary && summary !== headline && (
                <button
                    type="button"
                    className="self-start text-xs text-accent cursor-pointer bg-transparent border-0 p-0"
                    onClick={() => setSummaryExpanded(!summaryExpanded)}
                >
                    {summaryExpanded ? 'Show less' : 'Show more'}
                </button>
            )}

            <IssueFindingChips findings={issueFindings} />

            <div className="flex items-center gap-2">
                {cta === 'create_pr' && (
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        icon={<IconPullRequest />}
                        loading={isCreatingPr}
                        tooltip="Have Self-driving open a pull request for this report"
                        data-attr="error-tracking-issue-analysis-create-pr"
                        onClick={() => {
                            captureInboxReportAction({ report, actionType: 'create_pr', surface: 'issue_scene' })
                            createPrFromReport(report)
                        }}
                    >
                        Create fix PR
                    </LemonButton>
                )}
                {cta === 'view_pr' && prUrl && (
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        icon={<IconPullRequest />}
                        to={prUrl}
                        targetBlank
                        data-attr="error-tracking-issue-analysis-view-pr"
                    >
                        View fix PR
                    </LemonButton>
                )}
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    to={urls.inboxReport('reports', report.id)}
                    data-attr="error-tracking-issue-analysis-view-report"
                >
                    View full analysis
                </LemonButton>
            </div>
        </div>
    )
}

/** Suspect code paths and commits from this issue's `signal_finding` artefacts, capped for card display. */
function IssueFindingChips({ findings }: { findings: IssueFinding[] }): JSX.Element | null {
    const codePaths = Array.from(new Set(findings.flatMap((f) => f.codePaths)))
    const commits = findings.flatMap((f) => f.commits)
    if (!codePaths.length && !commits.length) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-1">
            {codePaths.slice(0, MAX_CODE_PATHS).map((path) => (
                <LemonTag key={path} size="small" className="font-mono max-w-full">
                    <span className="truncate" title={path}>
                        {path}
                    </span>
                </LemonTag>
            ))}
            {codePaths.length > MAX_CODE_PATHS && (
                <span className="text-xs text-tertiary">+{codePaths.length - MAX_CODE_PATHS} more</span>
            )}
            {commits.slice(0, MAX_COMMITS).map(({ sha, reason }) => (
                <Tooltip key={sha} title={reason || 'Suspect commit'}>
                    <LemonTag size="small" type="highlight" className="font-mono">
                        {sha.slice(0, 7)}
                    </LemonTag>
                </Tooltip>
            ))}
        </div>
    )
}
