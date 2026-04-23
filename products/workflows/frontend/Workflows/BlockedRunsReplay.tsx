import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { BlockedRun, blockedRunsLogic } from './blockedRunsLogic'

export function BlockedRunsReplay({ id }: { id: string }): JSX.Element {
    const logic = blockedRunsLogic({ id })
    const { allBlockedRuns, blockedRunsLoading, selectedRunIds, hasMoreRuns, replayAllLoading } = useValues(logic)
    const {
        toggleRunSelection,
        setSelectedRunIds,
        clearSelection,
        replaySelectedRuns,
        replayAllBlockedRuns,
        loadMoreBlockedRuns,
    } = useActions(logic)

    const selectedCount = selectedRunIds.size
    const allSelected = allBlockedRuns.length > 0 && allBlockedRuns.every((r) => selectedRunIds.has(r.instance_id))

    const confirmReplay = (): void => {
        LemonDialog.open({
            title: `Replay ${selectedCount} blocked run${selectedCount !== 1 ? 's' : ''}?`,
            description:
                'This will re-execute each workflow starting from the action that was blocked. Actions that completed before the block will not be re-executed. Workflow variables from prior steps will not be available.',
            primaryButton: {
                children: 'Replay',
                type: 'primary',
                onClick: () => replaySelectedRuns(),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const confirmReplayAll = (): void => {
        LemonDialog.open({
            title: 'Replay all blocked runs?',
            description:
                'This will re-execute all blocked workflow runs starting from their blocked action. This includes runs not yet loaded in this list. Actions that already completed will not be re-executed. Workflow variables from prior steps will not be available.',
            primaryButton: {
                children: 'Replay all',
                type: 'primary',
                status: 'danger',
                onClick: () => replayAllBlockedRuns(),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const columns: LemonTableColumns<BlockedRun> = [
        {
            title: (
                <LemonCheckbox
                    checked={allSelected ? true : selectedCount > 0 ? 'indeterminate' : false}
                    onChange={(checked) =>
                        checked
                            ? setSelectedRunIds(new Set(allBlockedRuns.map((r) => r.instance_id)))
                            : clearSelection()
                    }
                />
            ),
            width: 0,
            render: (_, run) => (
                <LemonCheckbox
                    checked={selectedRunIds.has(run.instance_id)}
                    onChange={() => toggleRunSelection(run.instance_id)}
                />
            ),
        },
        {
            title: 'Run ID',
            key: 'instance_id',
            render: (_, run) => <code className="text-xs">{run.instance_id}</code>,
        },
        {
            title: 'Event UUID',
            key: 'event_uuid',
            render: (_, run) =>
                run.event_uuid ? (
                    <code className="text-xs">{run.event_uuid}</code>
                ) : (
                    <span className="text-muted">-</span>
                ),
        },
        {
            title: 'Blocked action',
            key: 'action_id',
            render: (_, run) =>
                run.action_id ? (
                    <code className="text-xs">{run.action_id}</code>
                ) : (
                    <span className="text-muted">-</span>
                ),
        },
        {
            title: 'Blocked at',
            key: 'timestamp',
            render: (_, run) => <TZLabel time={run.timestamp} />,
        },
    ]

    if (blockedRunsLoading && allBlockedRuns.length === 0) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    return (
        <div className="space-y-4 p-4">
            <LemonBanner type="info">
                These workflow runs were blocked by a deduplication bug between March 30 and April 22. Replaying a run
                will re-execute the workflow starting from the blocked action — actions that already completed (e.g.
                emails sent) will not be re-executed. Note that workflow variables set by prior steps will not be
                available.
            </LemonBanner>

            <div className="flex items-center gap-2">
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    loading={replayAllLoading}
                    onClick={confirmReplayAll}
                >
                    Replay all blocked runs
                </LemonButton>
            </div>

            {selectedCount > 0 && (
                <div className="flex items-center gap-2">
                    <span className="text-muted text-sm">
                        {selectedCount} run{selectedCount !== 1 ? 's' : ''} selected
                    </span>
                    <LemonButton type="primary" size="small" onClick={confirmReplay}>
                        Replay selected
                    </LemonButton>
                    <LemonButton type="secondary" size="small" onClick={clearSelection}>
                        Clear selection
                    </LemonButton>
                </div>
            )}

            <LemonTable
                dataSource={allBlockedRuns}
                loading={blockedRunsLoading}
                columns={columns}
                rowKey="instance_id"
                pagination={{ pageSize: 20 }}
                nouns={['blocked run', 'blocked runs']}
                emptyState="No blocked runs found for this workflow"
            />

            {hasMoreRuns && (
                <div className="flex justify-center">
                    <LemonButton type="secondary" loading={blockedRunsLoading} onClick={loadMoreBlockedRuns}>
                        Load more
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
