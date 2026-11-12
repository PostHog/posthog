import { useActions } from 'kea'

import { IconFlag } from '@posthog/icons'
import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { pluralize } from 'lib/utils/strings'

import { AreaGroup, AreaRow, ownedShare, statusTag, touchesSensitivePath } from './areaDisplay'
import { AreaExpandedRow } from './AreaExpandedRow'
import { stamphogAreaSceneLogic } from './stamphogAreaSceneLogic'

function shareLabel(share: number): string {
    if (share >= 1) {
        return 'all of the change'
    }
    if (share < 0.01) {
        return 'less than 1% of the change'
    }
    return `${Math.round(share * 100)}% of the change`
}

export function AreaGroupTable({ group, rows }: { group: AreaGroup; rows: AreaRow[] }): JSX.Element {
    const { loadRunDetail } = useActions(stamphogAreaSceneLogic)

    const columns: LemonTableColumns<AreaRow> = [
        {
            key: 'flag',
            // Fixed widths keep the columns of every group's table in line with each other.
            width: 24,
            render: () =>
                group === 'needs_a_look' ? (
                    <IconFlag className="text-warning text-base" aria-label="Needs a look" />
                ) : null,
        },
        {
            key: 'change',
            render: (_, { run, decision }) => {
                const summary = decision.summary ?? run.pull_request.summary
                return (
                    <div className="flex flex-col gap-1 py-2 min-w-0">
                        <div className="flex items-baseline gap-2">
                            <Link to={run.pull_request.url} target="_blank" className="font-mono text-xs shrink-0">
                                #{run.pr_number}
                            </Link>
                            <span className="font-semibold">{run.pull_request.title}</span>
                        </div>
                        {summary ? (
                            <div>
                                {decision.summary ? <span className="text-secondary">Your part: </span> : null}
                                {summary}
                            </div>
                        ) : null}
                        {decision.top_files.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                                {decision.top_files.map((file) => (
                                    <code key={file.path} className="text-xs bg-surface-secondary rounded px-1 py-0.5">
                                        {file.path}
                                    </code>
                                ))}
                            </div>
                        ) : null}
                        <div className="text-xs text-secondary">
                            {run.pull_request.author}
                            {run.pull_request.merged_at ? (
                                <>
                                    {' · merged '}
                                    <TZLabel time={run.pull_request.merged_at} />
                                </>
                            ) : null}
                            {run.pull_request.approved_by_stamphog ? ' · approved by stamphog' : null}
                        </div>
                    </div>
                )
            },
        },
        {
            key: 'status',
            width: 240,
            render: (_, { decision }) => {
                const status = statusTag(decision.outcome)
                return (
                    <div className="flex flex-wrap justify-end gap-1">
                        <LemonTag type={status.type}>{status.label}</LemonTag>
                        {touchesSensitivePath(decision) ? <LemonTag type="danger">Sensitive path</LemonTag> : null}
                    </div>
                )
            },
        },
        {
            key: 'share',
            width: 200,
            render: (_, row) => {
                const share = ownedShare(row)
                return (
                    <div className="flex flex-col items-end gap-1 text-xs">
                        <span>
                            <span className="font-semibold">{pluralize(row.decision.lines ?? 0, 'line')}</span>
                            {` in ${pluralize(row.decision.file_count ?? 0, 'file')}`}
                        </span>
                        {share !== null ? (
                            <>
                                <LemonProgress percent={share * 100} strokeColor="var(--color-accent)" />
                                <span className="text-secondary">{shareLabel(share)}</span>
                            </>
                        ) : null}
                    </div>
                )
            },
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={rows}
            rowKey={(row) => row.run.id}
            showHeader={false}
            expandable={{
                expandedRowRender: (row) => <AreaExpandedRow row={row} />,
                onRowExpand: (row) => loadRunDetail(row.run.id),
            }}
            data-attr={`stamphog-area-group-${group}`}
        />
    )
}
