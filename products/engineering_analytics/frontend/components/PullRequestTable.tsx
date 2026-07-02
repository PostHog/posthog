// The one PR table of the lens stack, shared by the repo hub's attention slice and the PR list.
// Mock-locked column set: title (+repo#id, labels) · author · state (auto-hides when every row
// agrees) · CI with the failing workflow names under the tag · pushes (+re-runs) · CI cost ·
// open time. Only the default sort differs per caller. Author is attribution, not a lens — it
// renders as plain metadata and links nowhere in-product.

import { combineUrl, router } from 'kea-router'
import { ReactNode } from 'react'

import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
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

/** Hours below two days, one-decimal days above — how long the PR has been (or was) open. */
function openTimeOf(row: PullRequestRow): { seconds: number; label: string } {
    const end = row.mergedAt ?? (row.state === 'open' ? dayjs().toISOString() : null)
    const seconds = end ? dayjs(end).diff(dayjs(row.createdAt), 'second') : (row.openToMergeSeconds ?? 0)
    const hours = seconds / 3600
    return { seconds, label: hours < 48 ? `${Math.round(hours)}h` : `${(hours / 24).toFixed(1)}d` }
}

export interface PullRequestTableProps {
    rows: PullRequestRow[]
    loading: boolean
    /** Threaded into row links so the PR's detail page reads the same source. */
    sourceId: string | null
    /** Show the pushes / re-runs / CI cost columns. */
    costLensEnabled: boolean
    defaultSorting?: { columnKey: string; order: 1 | -1 }
    /** Rows per page — the list page's 50 by default; the hub passes a small page to stay scannable. */
    pageSize?: number
    emptyState?: ReactNode
    dataAttr?: string
}

export function PullRequestTable({
    rows,
    loading,
    sourceId,
    costLensEnabled,
    defaultSorting,
    pageSize = 50,
    emptyState,
    dataAttr = 'engineering-analytics-pr-table',
}: PullRequestTableProps): JSX.Element {
    // A State column where every row says "Open" is noise — only show it when states are mixed.
    const mixedStates = new Set(rows.map((row) => `${row.state}:${row.isDraft}`)).size > 1
    const columns: LemonTableColumns<PullRequestRow> = [
        {
            title: 'Pull request',
            key: 'title',
            render: (_, row) => (
                <div className="flex flex-col gap-0.5">
                    <Link to={detailUrlOf(row, sourceId)} className="font-medium">
                        {row.title}
                    </Link>
                    <div className="flex items-center gap-1.5 text-xs text-secondary">
                        <Link
                            to={githubPrUrl(row.repoOwner, row.repoName, row.number)}
                            target="_blank"
                            targetBlankIcon
                            className="font-mono text-[11px] text-tertiary"
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
            title: 'Author',
            key: 'author',
            width: 170,
            render: (_, row) => (
                <div className="flex items-center gap-1.5">
                    {row.authorAvatarUrl && (
                        <img src={row.authorAvatarUrl} alt="" className="size-5 shrink-0 rounded-full" />
                    )}
                    <span className="text-xs font-medium">{row.authorHandle}</span>
                    {row.isBot && <LemonTag type="muted">bot</LemonTag>}
                </div>
            ),
        },
        ...(mixedStates
            ? ([
                  {
                      title: 'State',
                      key: 'state',
                      width: 90,
                      render: (_, row) => <PullRequestStateTag state={row.state} isDraft={row.isDraft} />,
                  },
              ] as LemonTableColumns<PullRequestRow>)
            : []),
        {
            title: 'CI',
            key: 'ci',
            width: 190,
            render: (_, row) => (
                <div className="flex flex-col gap-0.5">
                    <CIStatusTag rollup={row} />
                    {row.failingWorkflows.length > 0 && (
                        <span className="text-[10.5px] leading-tight text-tertiary">
                            {row.failingWorkflows.slice(0, 3).join(' · ')}
                            {row.failingWorkflows.length > 3 && ` +${row.failingWorkflows.length - 3}`}
                        </span>
                    )}
                </div>
            ),
        },
        ...(costLensEnabled
            ? ([
                  {
                      title: 'Pushes',
                      key: 'pushes',
                      width: 100,
                      align: 'right',
                      tooltip:
                          'Distinct head commits that triggered CI for this PR, with re-run cycles as the amber tag. Fork PRs are unattributed.',
                      sorter: (a, b) => a.pushes - b.pushes,
                      render: (_, row) => (
                          <span className="text-xs tabular-nums whitespace-nowrap">
                              {humanFriendlyNumber(row.pushes)}
                              {row.rerunCycles > 0 && (
                                  <LemonTag type="warning" className="ml-1.5">
                                      +{row.rerunCycles}
                                  </LemonTag>
                              )}
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
        {
            title: 'Open time',
            key: 'age',
            width: 100,
            align: 'right',
            tooltip: 'How long the PR has been open — or was, until it merged.',
            sorter: (a, b) => openTimeOf(a).seconds - openTimeOf(b).seconds,
            render: (_, row) => (
                <Tooltip title={<>opened {dayjs(row.createdAt).format('MMM D, HH:mm')}</>}>
                    <span className="text-xs tabular-nums whitespace-nowrap">{openTimeOf(row).label}</span>
                </Tooltip>
            ),
        },
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
                    // Inner links (#id → GitHub) keep their own behavior.
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
            pagination={{ pageSize }}
            emptyState={emptyState ?? 'No pull requests yet — they show up as soon as CI events arrive.'}
            nouns={['pull request', 'pull requests']}
        />
    )
}
