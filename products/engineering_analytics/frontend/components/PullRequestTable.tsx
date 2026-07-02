// The PR list table, shared by the main PR list (Overview tab) and the author page (scoped to one
// author). Only the author column and default sort differ per caller.

import { combineUrl, router } from 'kea-router'
import { ReactNode } from 'react'

import { LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { githubPrUrl } from '../lib/github'
import { PullRequestRow, prKeyOf } from '../scenes/engineeringAnalyticsLogic'
import { BillableBadge } from './BillableBadge'
import { CIStatusTag } from './CIStatusTag'
import { PullRequestStateTag } from './PullRequestStateTag'

/** The PR's detail page, carrying the active source so it opens scoped to the same one. */
function detailUrlOf(row: PullRequestRow, sourceId: string | null): string {
    return combineUrl(
        urls.engineeringAnalyticsPullRequest(row.repoOwner, row.repoName, row.number),
        sourceId ? { source: sourceId } : {}
    ).url
}

export interface PullRequestTableProps {
    rows: PullRequestRow[]
    loading: boolean
    /** Threaded into row links so the PR's detail page reads the same source. */
    sourceId: string | null
    /** Show the pushes / re-runs / CI cost columns. */
    costLensEnabled: boolean
    /** Author column is redundant on the author page (every row is the same author) — hide it there. */
    showAuthor?: boolean
    defaultSorting?: { columnKey: string; order: 1 | -1 }
    emptyState?: ReactNode
    dataAttr?: string
}

export function PullRequestTable({
    rows,
    loading,
    sourceId,
    costLensEnabled,
    showAuthor = true,
    defaultSorting,
    emptyState,
    dataAttr = 'engineering-analytics-pr-table',
}: PullRequestTableProps): JSX.Element {
    const columns: LemonTableColumns<PullRequestRow> = [
        {
            title: 'Pull request',
            key: 'title',
            render: (_, row) => (
                <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                        <PullRequestStateTag state={row.state} isDraft={row.isDraft} />
                        <Link to={detailUrlOf(row, sourceId)} className="font-medium">
                            {row.title}
                        </Link>
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-secondary">
                        <Link
                            to={githubPrUrl(row.repoOwner, row.repoName, row.number)}
                            target="_blank"
                            targetBlankIcon
                            className="font-mono text-secondary"
                        >
                            {row.repoOwner}/{row.repoName} #{row.number}
                        </Link>
                        {row.labels.slice(0, 3).map((label) => (
                            <LemonTag key={label} type="option">
                                {label}
                            </LemonTag>
                        ))}
                    </div>
                </div>
            ),
        },
        {
            title: 'CI',
            key: 'ci',
            width: 190,
            render: (_, row) => <CIStatusTag rollup={row} />,
        },
        ...(showAuthor
            ? ([
                  {
                      title: 'Author',
                      key: 'author',
                      width: 190,
                      render: (_, row) => (
                          <div className="flex items-center gap-1.5">
                              {row.authorAvatarUrl && (
                                  <img src={row.authorAvatarUrl} alt="" className="h-5 w-5 shrink-0 rounded-full" />
                              )}
                              <Link
                                  to={
                                      combineUrl(
                                          urls.engineeringAnalyticsAuthor(row.authorHandle),
                                          sourceId ? { source: sourceId } : {}
                                      ).url
                                  }
                                  className="text-xs"
                              >
                                  {row.authorHandle}
                              </Link>
                              {row.isBot && <LemonTag type="muted">bot</LemonTag>}
                          </div>
                      ),
                  },
              ] as LemonTableColumns<PullRequestRow>)
            : []),
        {
            title: 'Opened',
            key: 'age',
            width: 130,
            align: 'right',
            sorter: (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime(),
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap">
                    <TZLabel time={row.createdAt} />
                </span>
            ),
        },
        {
            title: 'Open→merge',
            key: 'openToMerge',
            width: 130,
            align: 'right',
            sorter: (a, b) => (a.openToMergeSeconds ?? -1) - (b.openToMergeSeconds ?? -1),
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap text-secondary">
                    {row.openToMergeSeconds == null ? '—' : humanFriendlyDuration(row.openToMergeSeconds)}
                </span>
            ),
        },
        ...(costLensEnabled
            ? ([
                  {
                      title: 'Pushes',
                      key: 'pushes',
                      width: 90,
                      align: 'right',
                      tooltip:
                          'Distinct head commits that triggered CI for this PR (all-time, not windowed). Fork PRs are unattributed.',
                      sorter: (a, b) => a.pushes - b.pushes,
                      render: (_, row) => (
                          <span className="text-xs tabular-nums">{humanFriendlyNumber(row.pushes)}</span>
                      ),
                  },
                  {
                      title: 'Re-runs',
                      key: 'rerunCycles',
                      width: 90,
                      align: 'right',
                      tooltip: 'Workflow runs on this PR that were a 2nd+ attempt (a re-run).',
                      sorter: (a, b) => a.rerunCycles - b.rerunCycles,
                      render: (_, row) => (
                          <span className="text-xs tabular-nums">
                              {row.rerunCycles > 0 ? humanFriendlyNumber(row.rerunCycles) : '—'}
                          </span>
                      ),
                  },
                  {
                      title: 'CI cost',
                      key: 'estimatedCostUsd',
                      width: 130,
                      align: 'right',
                      tooltip:
                          'Billable minutes + estimated cost across this PR’s jobs (self-hosted runners) over its full history — not the selected window. Excludes still-running jobs, so it can rise as they settle. "—" when the job-level source isn’t synced.',
                      sorter: (a, b) => (a.estimatedCostUsd ?? -1) - (b.estimatedCostUsd ?? -1),
                      render: (_, row) => (
                          <BillableBadge minutes={row.billableMinutes} costUsd={row.estimatedCostUsd} />
                      ),
                  },
              ] as LemonTableColumns<PullRequestRow>)
            : []),
    ]

    return (
        <LemonTable
            data-attr={dataAttr}
            size="small"
            columns={columns}
            dataSource={rows}
            rowKey={prKeyOf}
            loading={loading}
            defaultSorting={defaultSorting}
            onRow={(row) => {
                const detailUrl = detailUrlOf(row, sourceId)
                return {
                    // Inner links (#id → GitHub, author → author page) keep their own behavior.
                    onClick: (e: React.MouseEvent) => {
                        if ((e.target as HTMLElement).closest('a, button')) {
                            return
                        }
                        if (e.metaKey || e.ctrlKey) {
                            e.preventDefault()
                            newInternalTab(detailUrl)
                        } else {
                            router.actions.push(detailUrl)
                        }
                    },
                    onAuxClick: (e: React.MouseEvent) => {
                        if (e.button === 1 && !(e.target as HTMLElement).closest('a, button')) {
                            e.preventDefault()
                            newInternalTab(detailUrl)
                        }
                    },
                }
            }}
            useURLForSorting={false}
            pagination={{ pageSize: 50 }}
            emptyState={emptyState ?? 'No pull requests yet — they show up as soon as CI events arrive.'}
            nouns={['pull request', 'pull requests']}
        />
    )
}
