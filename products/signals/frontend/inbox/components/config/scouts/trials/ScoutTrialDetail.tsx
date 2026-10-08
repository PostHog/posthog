import { IconArrowLeft, IconDownload, IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { ScoutRubricsButton } from '../ScoutRubricsButton'
import { ScoutTrialComparisonReport } from './ScoutTrialComparisonReport'
import type { ScoutTrialsViewProps } from './ScoutTrialsView'
import { trialIsActive, trialTaskIsActive } from './scoutTrialUtils'

export function ScoutTrialDetail(props: ScoutTrialsViewProps): JSX.Element {
    const { submitting, batch } = props
    const selectedConfig = props.configs?.find((config) => config.id === props.selectedConfigId)
    const trial = props.comparisonState.value
    return (
        <div className="flex min-w-0 flex-col gap-5">
            <div className="flex flex-col items-start gap-2">
                <LemonButton
                    type="tertiary"
                    size="small"
                    noPadding
                    icon={<IconArrowLeft />}
                    onClick={props.showTrialList}
                    disabledReason={submitting ? 'Wait for the trial to start.' : undefined}
                >
                    All trials
                </LemonButton>
                <div className="flex w-full flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                        <h2 className="m-0 text-lg font-semibold">{`Trial ${props.selectedComparison?.id.slice(0, 8)}`}</h2>
                        <p className="mb-0 mt-1 text-sm text-secondary">{`${props.selectedComparison?.groups.length ?? 0} versions · ${props.selectedComparison?.groups.reduce((count, group) => count + group.launchIds.length, 0) ?? 0} runs${trial?.created_at ? ` · ${dayjs(trial.created_at).format('MMM D, YYYY, HH:mm')}` : ''}`}</p>
                    </div>
                    <LemonButton
                        type="secondary"
                        onClick={props.newComparison}
                        disabledReason={
                            props.trialsDisabledReason || (submitting ? 'Wait for the trial to start.' : undefined)
                        }
                        data-attr="scout-comparison-new"
                    >
                        New trial
                    </LemonButton>
                </div>
            </div>
            {props.managedComparison ? (
                <>
                    {submitting ? (
                        <LemonBanner type="info">Starting trial…</LemonBanner>
                    ) : props.comparisonState.value?.status === 'judging' ? (
                        <LemonBanner type="info">
                            Judging the results against your saved rubrics. Your report will appear here automatically.
                            You can close this page.
                        </LemonBanner>
                    ) : props.comparisonState.value?.status === 'running' ||
                      props.comparisonState.value?.status === 'starting' ? (
                        <LemonBanner type="info">
                            Scouts are running. Judging starts automatically when every run finishes. You can close this
                            page and return to the saved report.
                        </LemonBanner>
                    ) : props.comparisonState.value?.status === 'unknown' ? (
                        <LemonBanner type="warning">
                            Trial status is unavailable. Refresh to check whether it is still running.
                        </LemonBanner>
                    ) : props.comparisonState.value?.status === 'not_started' ? (
                        <LemonBanner type="warning">
                            This trial is saved but has not started. Retry to continue with the same versions and run
                            IDs.
                        </LemonBanner>
                    ) : props.comparisonState.notStarted && !batch ? (
                        <LemonBanner type="warning">
                            This trial was not saved. Start a new trial to enter your versions again.
                        </LemonBanner>
                    ) : props.comparisonState.loading && !props.comparisonState.value ? (
                        <LemonSkeleton className="h-16" />
                    ) : null}
                    {(props.comparisonState.error || props.comparisonState.value?.error) && (
                        <LemonBanner type="error">
                            {props.comparisonState.error || props.comparisonState.value?.error}
                        </LemonBanner>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        {batch?.comparison.id === props.selectedComparison?.id && props.hasUnaccepted && (
                            <LemonButton
                                type="primary"
                                onClick={props.submitComparison}
                                loading={submitting}
                                disabledReason={props.trialsDisabledReason}
                                data-attr="scout-comparison-retry-start"
                            >
                                Retry starting trial
                            </LemonButton>
                        )}
                        {(props.comparisonState.value?.status === 'failed' ||
                            props.comparisonState.value?.status === 'not_started') && (
                            <LemonButton
                                type="secondary"
                                onClick={props.resumeComparison}
                                loading={props.comparisonState.resuming}
                                disabledReason={
                                    props.trialsDisabledReason ||
                                    (props.comparisonState.loading ? 'Wait for the current status.' : undefined)
                                }
                                data-attr="scout-comparison-resume"
                            >
                                Retry trial
                            </LemonButton>
                        )}
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            loading={props.comparisonState.loading || props.refreshing}
                            disabledReason={
                                submitting || props.comparisonState.resuming
                                    ? 'Wait for this request to finish.'
                                    : undefined
                            }
                            onClick={() => {
                                props.loadComparison(props.selectedComparison!.id)
                                props.refreshResults(true)
                            }}
                            data-attr="scout-comparison-refresh"
                        >
                            Refresh status
                        </LemonButton>
                        {selectedConfig && <ScoutRubricsButton config={selectedConfig} />}
                    </div>
                    {!props.evaluationState.value?.report && props.comparisonRows.length > 0 && (
                        <div className="flex flex-col gap-2">
                            <p className="m-0 text-sm font-semibold">Runs in this trial</p>
                            {props.comparisonRows.map((row) => (
                                <LemonCard
                                    key={row.launchId}
                                    hoverEffect={false}
                                    className="flex flex-wrap items-center justify-between gap-2 p-3"
                                >
                                    <div className="min-w-0 flex-1">
                                        <strong className="break-words">{row.variant}</strong>
                                        <p className="m-0 text-xs text-muted break-words">{`${row.model || 'Saved model'} · ${row.effort || 'default'} effort`}</p>
                                        {row.error && (
                                            <p className="m-0 text-xs text-danger break-words">{row.error}</p>
                                        )}
                                    </div>
                                    <LemonTag
                                        type={
                                            row.status === 'completed'
                                                ? 'success'
                                                : row.status === 'failed'
                                                  ? 'danger'
                                                  : 'muted'
                                        }
                                    >
                                        {row.status === 'not_started' ? 'Queued' : row.status.replaceAll('_', ' ')}
                                    </LemonTag>
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        onClick={() => props.selectResult(row.launchId)}
                                        disabledReason={!row.result ? 'Run details have not loaded yet.' : undefined}
                                    >
                                        Run details
                                    </LemonButton>
                                    {row.result?.task_id &&
                                        row.result.task_run_id &&
                                        (trialIsActive(row.status) || trialTaskIsActive(row.result.task_status)) && (
                                            <LemonButton
                                                size="xsmall"
                                                type="tertiary"
                                                status="danger"
                                                loading={props.canceling.includes(row.launchId)}
                                                onClick={() => props.cancelRun(row.launchId)}
                                            >
                                                Stop run
                                            </LemonButton>
                                        )}
                                </LemonCard>
                            ))}
                        </div>
                    )}
                </>
            ) : (
                <>
                    {!props.evaluationState.value?.report && (
                        <LemonBanner type="info">
                            These runs were saved before automatic judging, or are a new judging attempt. Start judging
                            to create their report. Model charges apply.
                        </LemonBanner>
                    )}
                    <div className="flex flex-wrap gap-2">
                        {!props.evaluationState.value?.report && (
                            <LemonButton
                                type="secondary"
                                onClick={props.scoreComparison}
                                loading={props.evaluationState.scoring}
                                disabledReason={props.scoreDisabledReason}
                            >
                                {props.evaluationState.value?.status === 'failed'
                                    ? 'Retry judging'
                                    : 'Judge saved runs'}
                            </LemonButton>
                        )}
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            loading={props.evaluationState.loading}
                            disabledReason={
                                props.evaluationState.scoring ? 'Wait for judging to be submitted.' : undefined
                            }
                            onClick={() => props.loadEvaluation(props.selectedComparison!.id)}
                        >
                            Refresh status
                        </LemonButton>
                    </div>
                    {props.evaluationState.error && (
                        <LemonBanner type="error">{props.evaluationState.error}</LemonBanner>
                    )}
                    {props.evaluationState.value?.error && (
                        <LemonBanner type="error">{props.evaluationState.value.error}</LemonBanner>
                    )}
                    {(props.evaluationState.value?.status === 'pending' ||
                        props.evaluationState.value?.status === 'running') && (
                        <LemonBanner type="info">
                            Judging is in progress. The saved report will appear here automatically.
                        </LemonBanner>
                    )}
                    {props.evaluationState.value?.status === 'unknown' && (
                        <LemonBanner type="warning">
                            Judging status is unavailable. Refresh before retrying.
                        </LemonBanner>
                    )}
                </>
            )}
            {props.evaluationState.value?.report && (
                <>
                    <ScoutTrialComparisonReport
                        report={props.evaluationState.value.report}
                        rows={props.comparisonRows}
                        onSelectRun={props.selectResult}
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconDownload />}
                        onClick={props.downloadEvaluation}
                    >
                        Download report
                    </LemonButton>
                </>
            )}
            {(props.evaluationState.value?.status === 'completed' ||
                props.evaluationState.value?.status === 'failed') && (
                <LemonCollapse
                    panels={[
                        {
                            key: 'judge-again',
                            header: 'Judge these runs again',
                            content: (
                                <div className="flex flex-col gap-2 items-start">
                                    <p className="m-0 text-sm">
                                        Use your current saved rubrics to judge these same runs again. The original
                                        report stays available. This incurs additional model charges.
                                    </p>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={props.newScoringAttempt}
                                        disabledReason={
                                            props.trialsDisabledReason ||
                                            (props.evaluationState.loading || props.evaluationState.scoring
                                                ? 'Wait for the current status.'
                                                : undefined)
                                        }
                                    >
                                        Prepare another judging attempt
                                    </LemonButton>
                                </div>
                            ),
                        },
                    ]}
                />
            )}
        </div>
    )
}
