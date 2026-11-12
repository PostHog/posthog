import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { pluralize } from 'lib/utils/strings'

import { RoutingOwnerOutcomeEnumApi, StamphogRoutingRunApi } from '../../generated/api.schemas'
import { ExpandedRoutingRunDetails } from './ExpandedRoutingRunDetails'
import { ownerDecision, reasonLabel } from './routingRunDisplay'
import { TEAM_VIEW_PAGE_SIZE, stamphogTeamViewSceneLogic } from './stamphogTeamViewSceneLogic'

export function TeamViewTable(): JSX.Element {
    const { owner, merged, runs, runsResponse, pullRequestCount, runsResponseLoading, runsFailed, page } =
        useValues(stamphogTeamViewSceneLogic)
    const { setPage, loadRuns } = useActions(stamphogTeamViewSceneLogic)

    if (!owner) {
        return (
            <LemonBanner type="info" data-attr="stamphog-team-view-no-team">
                Enter a team slug from owners.yaml, such as team-devex, or a GitHub login, such as @octocat, to see the
                pull requests that changed code it owns.
            </LemonBanner>
        )
    }

    if (runsFailed) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadRuns() }}
                data-attr="stamphog-team-view-error"
            >
                Could not load pull requests. This is usually temporary.
            </LemonBanner>
        )
    }

    const columns: LemonTableColumns<StamphogRoutingRunApi> = [
        {
            title: 'Pull request',
            key: 'pull_request',
            render: (_, run) => (
                <div className="flex items-baseline gap-2 min-w-60">
                    <Link to={run.pull_request.url} target="_blank" className="font-mono text-xs shrink-0">
                        #{run.pr_number}
                    </Link>
                    <span>{run.pull_request.title}</span>
                </div>
            ),
        },
        {
            title: 'Author',
            key: 'author',
            render: (_, run) => <span className="font-mono text-xs whitespace-nowrap">{run.pull_request.author}</span>,
        },
        merged
            ? {
                  title: 'Merged',
                  key: 'merged_at',
                  render: (_, run) =>
                      run.pull_request.merged_at ? <TZLabel time={run.pull_request.merged_at} /> : null,
              }
            : {
                  title: 'Routed',
                  key: 'created_at',
                  render: (_, run) => (run.created_at ? <TZLabel time={run.created_at} /> : null),
              },
        {
            title: 'Size',
            key: 'size',
            render: (_, run) =>
                // GitHub reports the size only when the pull request merges.
                run.pull_request.merged_at ? (
                    <span className="font-mono text-xs whitespace-nowrap">
                        <span className="text-success">{`+${run.pull_request.additions ?? 0}`}</span>{' '}
                        <span className="text-danger">{`-${run.pull_request.deletions ?? 0}`}</span>{' '}
                        <span className="text-muted">{`in ${pluralize(run.pull_request.changed_files ?? 0, 'file')}`}</span>
                    </span>
                ) : (
                    <span className="text-muted">-</span>
                ),
        },
        {
            title: 'Decision',
            key: 'decision',
            render: (_, run) => {
                const decision = ownerDecision(run, owner)
                if (!decision) {
                    return null
                }
                return (
                    <div className="flex flex-col gap-1 min-w-0 py-1">
                        <LemonTag type="option" className="self-start">
                            {reasonLabel(decision.reason)}
                        </LemonTag>
                        {decision.outcome === RoutingOwnerOutcomeEnumApi.Cut && decision.model_reason ? (
                            <span className="text-xs text-secondary">{decision.model_reason}</span>
                        ) : null}
                    </div>
                )
            },
        },
        {
            title: 'Owned',
            key: 'owned',
            render: (_, run) => {
                const decision = ownerDecision(run, owner)
                if (!decision) {
                    return null
                }
                return (
                    <span className="font-mono text-xs whitespace-nowrap">
                        {`${pluralize(decision.lines ?? 0, 'line')} in ${pluralize(decision.file_count ?? 0, 'file')}`}
                    </span>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="text-secondary text-sm">
                {runsResponseLoading || !runsResponse ? (
                    <span>Loading pull requests</span>
                ) : (
                    <span data-attr="stamphog-team-view-count">{pluralize(pullRequestCount, 'pull request')}</span>
                )}
            </div>
            <LemonTable
                columns={columns}
                dataSource={runs}
                loading={runsResponseLoading || !runsResponse}
                rowKey="id"
                expandable={{ expandedRowRender: (run) => <ExpandedRoutingRunDetails run={run} owner={owner} /> }}
                pagination={{
                    controlled: true,
                    pageSize: TEAM_VIEW_PAGE_SIZE,
                    currentPage: page,
                    entryCount: pullRequestCount,
                    onForward: () => setPage(page + 1),
                    onBackward: () => setPage(page - 1),
                }}
                emptyState={`No pull requests for ${owner} in this window. Check the spelling against owners.yaml, or pick a longer window.`}
            />
        </div>
    )
}
