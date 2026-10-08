import { IconPlus, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

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
        <div className="flex min-w-0 flex-col gap-5">
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
            <LemonTable<ScoutTrialComparison>
                dataSource={props.comparisonsForConfig}
                rowKey="id"
                loading={props.comparisonHistoryLoading && !props.comparisonsForConfig.length}
                emptyState="No trials yet. Create a trial to compare prompts, models, or effort."
                columns={[
                    {
                        title: 'Trial',
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
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Versions',
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
                        render: (_, trial) => {
                            const status = props.comparisonStates[trial.id]?.value?.status
                            return (
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
                            )
                        },
                    },
                ]}
            />
            {props.comparisonHistory?.has_more && (
                <p className="m-0 text-xs text-secondary">
                    Showing your 30 most recent trials, plus trials saved in this browser.
                </p>
            )}
            <p className="m-0 text-xs text-secondary">
                Trials and their results are private to you. Your live scout stays unchanged.
            </p>
        </div>
    )
}
