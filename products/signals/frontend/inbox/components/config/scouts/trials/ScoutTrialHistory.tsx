import { IconArchive, IconPlus, IconRefresh, IconUndo } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { ScoutTrialsViewProps } from './ScoutTrialsView'
import type { ScoutTrialComparison } from './scoutTrialUtils'

const STATUS_LABELS: Record<string, string> = {
    starting: 'Starting',
    running: 'Running',
    judging: 'Judging',
    completed: 'Completed',
    failed: 'Failed',
    not_started: 'Not started',
    unknown: 'Status unavailable',
}

export function ScoutTrialHistory(props: ScoutTrialsViewProps): JSX.Element {
    return (
        <div className="@container/trial-history flex min-w-0 flex-col gap-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1 basis-72">
                    <h2 className="m-0 text-lg font-semibold">Trials</h2>
                    <p className="mb-0 mt-1 text-sm text-secondary">
                        Compare versions of this scout. Runs happen in parallel, then the saved rubric grades each one.
                    </p>
                </div>
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        loading={props.comparisonHistoryLoading}
                        onClick={() => props.loadComparisonHistory(props.selectedConfigId!)}
                        aria-label="Refresh trials"
                    />
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={props.newComparison}
                        disabledReason={
                            props.trialsDisabledReason ||
                            (props.submitting
                                ? 'Wait for the trial to start.'
                                : props.setupLoading
                                  ? 'Loading scout settings.'
                                  : undefined)
                        }
                        data-attr="scout-comparison-new"
                    >
                        New trial
                    </LemonButton>
                </div>
            </div>
            <LemonSwitch
                checked={props.showArchived}
                onChange={props.setShowArchived}
                label="Show archived"
                className="self-start"
                data-attr="scout-trials-show-archived"
            />
            <LemonTable<ScoutTrialComparison>
                dataSource={props.comparisonsForConfig}
                rowKey="id"
                loading={props.comparisonHistoryLoading && !props.comparisonsForConfig.length}
                nouns={['trial', 'trials']}
                pagination={{
                    controlled: true,
                    useUrl: false,
                    hideOnSinglePage: !props.comparisonHistoryCursors.length && !props.comparisonHistory?.next_cursor,
                    onForward:
                        props.comparisonHistory?.next_cursor && !props.comparisonHistoryLoading
                            ? props.nextComparisonHistoryPage
                            : undefined,
                    onBackward:
                        props.comparisonHistoryCursors.length && !props.comparisonHistoryLoading
                            ? props.previousComparisonHistoryPage
                            : undefined,
                }}
                emptyState={
                    props.showArchived
                        ? 'No trials yet. Create a trial to compare prompts, models, or effort.'
                        : 'No trials to show. Create a trial or turn on Show archived.'
                }
                tableLayout="fixed"
                columns={[
                    {
                        title: 'Trial',
                        width: '28%',
                        render: (_, trial) => {
                            const saved = props.comparisonStates[trial.id]?.value
                            return (
                                <div className="flex min-w-0 flex-col items-start gap-1">
                                    <LemonButton
                                        type="tertiary"
                                        size="small"
                                        noPadding
                                        onClick={() => props.selectComparison(props.selectedConfigId!, trial.id)}
                                    >
                                        {`Trial ${trial.id.slice(0, 8)}`}
                                    </LemonButton>
                                    {saved?.created_at && (
                                        <span className="text-xs text-secondary">
                                            {dayjs(saved.created_at).format('MMM D, YYYY, HH:mm')}
                                        </span>
                                    )}
                                    {props.archiveErrors[trial.id] && (
                                        <span className="text-xs text-danger break-words">
                                            {props.archiveErrors[trial.id]}
                                        </span>
                                    )}
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Versions',
                        width: '32%',
                        render: (_, trial) => (
                            <div className="flex flex-col gap-1">
                                <span>{`${trial.groups.length} versions · ${trial.groups.reduce((count, group) => count + group.launchIds.length, 0)} runs`}</span>
                                <span className="text-xs text-secondary break-words">
                                    {props.comparisonStates[trial.id]?.value?.variants
                                        .map((version) => version.label)
                                        .join(' · ')}
                                </span>
                            </div>
                        ),
                    },
                    {
                        title: 'Status',
                        width: '22%',
                        render: (_, trial) => {
                            const status = props.comparisonStates[trial.id]?.value?.status
                            return (
                                <div className="flex flex-wrap gap-1">
                                    <LemonTag
                                        type={
                                            status === 'completed'
                                                ? 'success'
                                                : status === 'failed'
                                                  ? 'danger'
                                                  : status === 'judging' || status === 'running'
                                                    ? 'primary'
                                                    : 'muted'
                                        }
                                        wrap
                                    >
                                        {STATUS_LABELS[status ?? 'unknown'] ?? 'Status unavailable'}
                                    </LemonTag>
                                    {props.comparisonStates[trial.id]?.value?.archived && (
                                        <LemonTag type="muted">Archived</LemonTag>
                                    )}
                                </div>
                            )
                        },
                    },
                    {
                        title: '',
                        width: '18%',
                        render: (_, trial) => {
                            const state = props.comparisonStates[trial.id]
                            const saved = state?.value
                            return (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={saved?.archived ? <IconUndo /> : <IconArchive />}
                                    tooltip={saved?.archived ? 'Restore trial' : 'Archive trial'}
                                    loading={props.archiving.includes(trial.id)}
                                    disabledReason={
                                        state?.loading || state?.resuming
                                            ? 'Wait for the current status.'
                                            : !saved?.archived &&
                                                saved?.status !== 'completed' &&
                                                saved?.status !== 'failed'
                                              ? 'Only completed or failed trials can be archived.'
                                              : undefined
                                    }
                                    onClick={() => props.archiveComparison(trial.id, !saved?.archived)}
                                    aria-label={`${saved?.archived ? 'Restore' : 'Archive'} trial ${trial.id.slice(0, 8)}`}
                                    data-attr="scout-trial-archive"
                                >
                                    <span className="hidden @3xl/trial-history:inline">
                                        {saved?.archived ? 'Restore' : 'Archive'}
                                    </span>
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
            <p className="m-0 text-xs text-secondary">
                Trials and their results are private to you. Your live scout stays unchanged.
            </p>
        </div>
    )
}
