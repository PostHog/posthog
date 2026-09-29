import { IconDownload, IconPlus, IconRefresh } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { scoutTrialsLogicActions, scoutTrialsLogicValues } from '../../../../logics/scoutTrialsLogic'
import { scoutDisplayName } from '../../../../utils/scoutRunsWindow'
import { ScoutRubricsButton } from '../ScoutRubricsButton'
import { ScoutTrialComparisonReport } from './ScoutTrialComparisonReport'
import { ScoutTrialResultModal } from './ScoutTrialResultModal'
import { MAX_TRIAL_RUNS, ScoutTrialRow, trialIsActive, trialTaskIsActive } from './scoutTrialUtils'
import { ScoutTrialVariantEditor } from './ScoutTrialVariantEditor'

type ViewAction =
    | 'loadConfigs'
    | 'loadSetup'
    | 'loadHistory'
    | 'selectConfig'
    | 'updateVariant'
    | 'addVariant'
    | 'removeVariant'
    | 'setRepeats'
    | 'setNote'
    | 'submitComparison'
    | 'newComparison'
    | 'refreshResults'
    | 'selectResult'
    | 'downloadResults'
    | 'cancelRun'
    | 'selectComparison'
    | 'loadEvaluation'
    | 'scoreComparison'
    | 'newScoringAttempt'
    | 'downloadEvaluation'
    | 'loadComparison'
    | 'resumeComparison'
    | 'loadComparisonHistory'

export type ScoutTrialsViewProps = scoutTrialsLogicValues & {
    [Action in ViewAction]: (...args: Parameters<scoutTrialsLogicActions[Action]>) => void
}

export function ScoutTrialsView(props: ScoutTrialsViewProps): JSX.Element {
    const {
        configs,
        configsLoading,
        selectedConfigId,
        setup,
        setupLoading,
        pageError,
        variants,
        batch,
        submitting,
        totalRuns,
        rows,
    } = props
    const locked = submitting || !!batch
    const currentSetup = setup?.config_id === selectedConfigId ? setup : null
    const showSetup = props.editingComparison || (!props.selectedComparison && !props.comparisonHistoryLoading)
    const runCountLabel = `${totalRuns} ${totalRuns === 1 ? 'run' : 'runs'}`
    const selectedConfig = configs?.find((config) => config.id === selectedConfigId)

    return (
        <div className="@container flex flex-1 min-h-0 min-w-0 flex-col overflow-auto ph-no-capture ph-replay-block">
            <div className="p-4 flex flex-col gap-4 max-w-5xl w-full mx-auto">
                <div className="flex flex-wrap items-center gap-2">
                    <h2 className="m-0 text-lg font-semibold">Scout comparisons</h2>
                    <LemonTag type="muted">Internal</LemonTag>
                </div>
                <p className="m-0 text-sm text-muted">
                    Compare prompts, models, and effort using the same saved rubrics. Scouts run in parallel, then a
                    judge checks their results automatically.
                </p>

                {pageError && (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: () => (selectedConfigId ? props.loadSetup(selectedConfigId) : props.loadConfigs()),
                            loading: configsLoading || setupLoading,
                        }}
                    >
                        {pageError}
                    </LemonBanner>
                )}
                {!configs ? (
                    configsLoading && <LemonSkeleton className="h-12" />
                ) : configs.length === 0 ? (
                    <LemonBanner type="info">
                        No scouts are available. Add a scout from the Scouts page, then return here.
                    </LemonBanner>
                ) : (
                    <LemonField.Pure label="Scout">
                        <LemonSelect
                            value={selectedConfigId}
                            options={configs.map((config) => ({ value: config.id, label: scoutDisplayName(config) }))}
                            onChange={(configId) => props.selectConfig(configId!)}
                            disabledReason={submitting ? 'Wait for all submissions to finish.' : undefined}
                            fullWidth
                            menu={{ className: 'ph-no-capture ph-replay-block' }}
                            dropdownMatchSelectWidth
                        />
                    </LemonField.Pure>
                )}

                {selectedConfigId && (setupLoading || !currentSetup) && !pageError && (
                    <LemonSkeleton className="h-64" />
                )}
                {currentSetup && !currentSetup.ready && (
                    <LemonBanner type="warning">
                        {currentSetup.blocked_reason || 'Comparisons are not enabled for this scout yet.'}
                    </LemonBanner>
                )}
                {currentSetup?.ready && showSetup && (
                    <>
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonTag type="muted">Saved rubrics</LemonTag>
                            {selectedConfig && <ScoutRubricsButton config={selectedConfig} />}
                            <span className="text-xs text-muted">The same checklist grades every variant.</span>
                        </div>
                        <div className="flex flex-wrap gap-2 items-center justify-between">
                            <h3 className="m-0 text-base">Variants</h3>
                            <span className="text-xs text-muted">{`Saved skill version ${currentSetup.skill_version}`}</span>
                        </div>
                        <div className="grid grid-cols-1 @3xl:grid-cols-2 gap-3">
                            {variants.map((variant, index) => (
                                <ScoutTrialVariantEditor
                                    key={variant.id}
                                    variant={variant}
                                    setup={currentSetup}
                                    locked={locked}
                                    removable={index > 0}
                                    update={(update) => props.updateVariant(variant.id, update)}
                                    remove={() => props.removeVariant(variant.id)}
                                />
                            ))}
                        </div>
                        <div className="flex flex-wrap gap-3 items-center">
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={<IconPlus />}
                                onClick={props.addVariant}
                                disabledReason={
                                    locked
                                        ? 'Start a new comparison to add variants.'
                                        : variants.length >= 10
                                          ? 'Use up to 10 variants per comparison.'
                                          : undefined
                                }
                            >
                                Add variant
                            </LemonButton>
                            <span className="text-xs text-muted">
                                The baseline is editable too. The production scout stays unchanged.
                            </span>
                        </div>
                        <LemonField.Pure
                            label="Instructions for every run"
                            showOptional
                            help="For example, focus on the last 7 days or investigate a repository. These guide the scout; they do not restrict which data its tools can access."
                        >
                            <LemonTextArea
                                value={props.note}
                                onChange={props.setNote}
                                maxLength={1000}
                                minRows={2}
                                maxRows={6}
                                disabled={locked}
                                placeholder="Focus on…"
                            />
                        </LemonField.Pure>
                        <div className="flex flex-wrap gap-4 items-end">
                            <LemonField.Pure label="Runs per variant" className="w-40">
                                <LemonInput
                                    type="number"
                                    value={props.repeats}
                                    min={1}
                                    max={MAX_TRIAL_RUNS}
                                    step={1}
                                    onChange={(value) => props.setRepeats(value ?? 1)}
                                    disabledReason={
                                        locked ? 'Start a new comparison to change the run count.' : undefined
                                    }
                                />
                            </LemonField.Pure>
                            <span className="text-sm pb-2">{`${runCountLabel} total · maximum ${MAX_TRIAL_RUNS}`}</span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            {(!batch || props.hasUnaccepted) && (
                                <LemonButton
                                    type="primary"
                                    onClick={props.submitComparison}
                                    loading={submitting}
                                    disabledReason={batch ? undefined : props.formError}
                                    data-attr="scout-comparison-start"
                                >
                                    {batch ? 'Retry starting comparison' : 'Start comparison'}
                                </LemonButton>
                            )}
                            {props.selectedComparison && props.editingComparison && (
                                <LemonButton
                                    type="secondary"
                                    onClick={() =>
                                        props.selectComparison(selectedConfigId!, props.selectedComparison!.id)
                                    }
                                >
                                    Back to results
                                </LemonButton>
                            )}
                            {batch && (
                                <LemonButton
                                    type="secondary"
                                    onClick={props.newComparison}
                                    disabledReason={submitting ? 'Wait for the comparison to be accepted.' : undefined}
                                >
                                    New comparison
                                </LemonButton>
                            )}
                        </div>
                        <p className="m-0 text-xs text-muted">
                            Runs and judging continue after you close this page. Each run starts with the same saved
                            history; new reports and memory stay private. Live data can change during a comparison. Both
                            scouts and judging incur model charges.
                        </p>
                    </>
                )}

                {props.comparisonHistoryLoading && !props.selectedComparison && <LemonSkeleton className="h-20" />}
                {selectedConfigId && props.selectedComparison && !props.editingComparison && (
                    <div className="flex flex-col gap-3 border-t pt-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h3 className="m-0 text-base">
                                {props.evaluationState.value?.report ? 'Comparison results' : 'Current comparison'}
                            </h3>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={props.newComparison}
                                disabledReason={submitting ? 'Wait for the comparison to be accepted.' : undefined}
                                data-attr="scout-comparison-new"
                            >
                                New comparison
                            </LemonButton>
                        </div>
                        <LemonField.Pure label="Comparison history">
                            <LemonSelect
                                value={props.selectedComparison.id}
                                options={props.comparisonsForConfig.map((comparison) => {
                                    const saved = props.comparisonStates[comparison.id]?.value
                                    return {
                                        value: comparison.id,
                                        label: `${saved?.created_at ? dayjs(saved.created_at).format('MMM D, HH:mm') : 'Saved comparison'} · ${comparison.groups.length} variants · ${comparison.groups.reduce((count, group) => count + group.launchIds.length, 0)} runs · ${comparison.id.slice(0, 8)}`,
                                    }
                                })}
                                onChange={(id) => props.selectComparison(selectedConfigId, id!)}
                                disabledReason={submitting ? 'Wait for the comparison to be accepted.' : undefined}
                                fullWidth
                                menu={{ className: 'ph-no-capture ph-replay-block' }}
                            />
                        </LemonField.Pure>
                        {props.managedComparison ? (
                            <>
                                {submitting ? (
                                    <LemonBanner type="info">Starting comparison…</LemonBanner>
                                ) : props.comparisonState.value?.status === 'judging' ? (
                                    <LemonBanner type="info">
                                        Judging the results against your saved rubrics. Your report will appear here
                                        automatically. You can close this page.
                                    </LemonBanner>
                                ) : props.comparisonState.value?.status === 'running' ||
                                  props.comparisonState.value?.status === 'starting' ? (
                                    <LemonBanner type="info">
                                        Scouts are running. Judging starts automatically when every run finishes. You
                                        can close this page and return to the saved report.
                                    </LemonBanner>
                                ) : props.comparisonState.value?.status === 'unknown' ? (
                                    <LemonBanner type="warning">
                                        Comparison status is unavailable. Refresh to check whether it is still running.
                                    </LemonBanner>
                                ) : props.comparisonState.value?.status === 'not_started' ? (
                                    <LemonBanner type="warning">
                                        This comparison is saved but has not started. Retry to continue with the same
                                        variants and run IDs.
                                    </LemonBanner>
                                ) : props.comparisonState.notStarted && !batch ? (
                                    <LemonBanner type="warning">
                                        This comparison was not saved. Start a new comparison to enter your variants
                                        again.
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
                                    {batch?.comparison.id === props.selectedComparison.id && props.hasUnaccepted && (
                                        <LemonButton
                                            type="primary"
                                            onClick={props.submitComparison}
                                            loading={submitting}
                                            data-attr="scout-comparison-retry-start"
                                        >
                                            Retry starting comparison
                                        </LemonButton>
                                    )}
                                    {(props.comparisonState.value?.status === 'failed' ||
                                        props.comparisonState.value?.status === 'not_started') && (
                                        <LemonButton
                                            type="secondary"
                                            onClick={props.resumeComparison}
                                            loading={props.comparisonState.resuming}
                                            disabledReason={
                                                props.comparisonState.loading
                                                    ? 'Wait for the current status.'
                                                    : undefined
                                            }
                                            data-attr="scout-comparison-resume"
                                        >
                                            Retry comparison
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
                                        <p className="m-0 text-sm font-semibold">Runs in this comparison</p>
                                        {props.comparisonRows.map((row) => (
                                            <div
                                                key={row.launchId}
                                                className="flex flex-wrap items-center justify-between gap-2 rounded border p-2"
                                            >
                                                <div className="min-w-0 flex-1">
                                                    <strong className="break-words">{row.variant}</strong>
                                                    <p className="m-0 text-xs text-muted break-words">{`${row.model || 'Saved model'} · ${row.effort || 'default'} effort`}</p>
                                                    {row.error && (
                                                        <p className="m-0 text-xs text-danger break-words">
                                                            {row.error}
                                                        </p>
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
                                                    {row.status === 'not_started'
                                                        ? 'Queued'
                                                        : row.status.replaceAll('_', ' ')}
                                                </LemonTag>
                                                <LemonButton
                                                    size="xsmall"
                                                    type="tertiary"
                                                    onClick={() => props.selectResult(row.launchId)}
                                                    disabledReason={
                                                        !row.result ? 'Run details have not loaded yet.' : undefined
                                                    }
                                                >
                                                    Run details
                                                </LemonButton>
                                                {row.result?.task_id &&
                                                    row.result.task_run_id &&
                                                    (trialIsActive(row.status) ||
                                                        trialTaskIsActive(row.result.task_status)) && (
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
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </>
                        ) : (
                            <>
                                {!props.evaluationState.value?.report && (
                                    <LemonBanner type="info">
                                        These runs were saved before automatic judging, or are a new judging attempt.
                                        Start judging to create their report. Model charges apply.
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
                                            props.evaluationState.scoring
                                                ? 'Wait for judging to be submitted.'
                                                : undefined
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
                                <ScoutTrialComparisonReport report={props.evaluationState.value.report} />
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
                                                    Use your current saved rubrics to judge these same runs again. The
                                                    original report stays available. This incurs additional model
                                                    charges.
                                                </p>
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    onClick={props.newScoringAttempt}
                                                    disabledReason={
                                                        props.evaluationState.loading || props.evaluationState.scoring
                                                            ? 'Wait for the current status.'
                                                            : undefined
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
                )}

                {selectedConfigId && (
                    <LemonCollapse
                        panels={[
                            {
                                key: 'run-history',
                                header: 'Individual run history',
                                content: (
                                    <div className="flex flex-col gap-3 border-t pt-4">
                                        <div className="flex flex-wrap items-center justify-between gap-2">
                                            <h3 className="m-0 text-base">Recent executions</h3>
                                            <div className="flex flex-wrap gap-2">
                                                <LemonButton
                                                    size="small"
                                                    type="secondary"
                                                    icon={<IconRefresh />}
                                                    loading={props.refreshing || props.historyLoading}
                                                    onClick={() => {
                                                        props.refreshResults(true)
                                                        props.loadHistory(selectedConfigId)
                                                        props.loadComparisonHistory(selectedConfigId)
                                                    }}
                                                >
                                                    Refresh
                                                </LemonButton>
                                                <LemonButton
                                                    size="small"
                                                    type="secondary"
                                                    icon={<IconDownload />}
                                                    onClick={props.downloadResults}
                                                    disabledReason={
                                                        !rows.some((row) => row.result)
                                                            ? 'No results have loaded yet.'
                                                            : undefined
                                                    }
                                                >
                                                    Download results
                                                </LemonButton>
                                            </div>
                                        </div>
                                        {props.pollError && <LemonBanner type="warning">{props.pollError}</LemonBanner>}
                                        <LemonTable<ScoutTrialRow>
                                            dataSource={rows}
                                            rowKey="launchId"
                                            tableLayout="fixed"
                                            size="small"
                                            loading={props.historyLoading && !rows.length}
                                            emptyState="No comparison runs yet. Choose variants above to start."
                                            columns={[
                                                {
                                                    title: 'Run',
                                                    width: '50%',
                                                    render: (_, row) => (
                                                        <div className="min-w-0">
                                                            <strong className="break-words">{row.variant}</strong>
                                                            <div className="text-xs text-muted break-all">
                                                                {row.model
                                                                    ? `${row.model} · ${row.effort}`
                                                                    : row.launchId}
                                                            </div>
                                                            {row.startedAt && (
                                                                <div className="text-xs text-muted">
                                                                    {dayjs(row.startedAt).format('MMM D, HH:mm')}
                                                                </div>
                                                            )}
                                                            {row.error && (
                                                                <div className="text-xs text-danger break-words">
                                                                    {row.error}
                                                                </div>
                                                            )}
                                                        </div>
                                                    ),
                                                },
                                                {
                                                    title: 'Status',
                                                    width: '27%',
                                                    render: (_, row) => (
                                                        <div className="flex flex-col items-start gap-1">
                                                            <LemonTag
                                                                type={
                                                                    row.status === 'completed'
                                                                        ? 'success'
                                                                        : row.status === 'failed' ||
                                                                            row.status === 'submission_failed'
                                                                          ? 'danger'
                                                                          : trialIsActive(row.status)
                                                                            ? 'primary'
                                                                            : 'muted'
                                                                }
                                                                wrap
                                                            >
                                                                {row.status.replaceAll('_', ' ')}
                                                            </LemonTag>
                                                            {row.result && (
                                                                <>
                                                                    <span className="text-xs">{`${row.result.reports.length} ${row.result.reports.length === 1 ? 'report' : 'reports'}`}</span>
                                                                    <span className="text-xs text-muted">
                                                                        {row.result.cost_usd === null
                                                                            ? 'Cost unknown'
                                                                            : `$${row.result.cost_usd.toFixed(2)}`}
                                                                    </span>
                                                                </>
                                                            )}
                                                        </div>
                                                    ),
                                                },
                                                {
                                                    title: '',
                                                    width: '23%',
                                                    render: (_, row) => (
                                                        <div className="flex flex-col items-start gap-1">
                                                            <LemonButton
                                                                size="xsmall"
                                                                type="tertiary"
                                                                onClick={() => props.selectResult(row.launchId)}
                                                                disabledReason={
                                                                    !row.result
                                                                        ? 'Results have not loaded yet.'
                                                                        : undefined
                                                                }
                                                            >
                                                                Results
                                                            </LemonButton>
                                                            {row.result?.task_id &&
                                                                row.result.task_run_id &&
                                                                (trialIsActive(row.status) ||
                                                                    trialTaskIsActive(row.result.task_status)) && (
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
                                                        </div>
                                                    ),
                                                },
                                            ]}
                                        />
                                        {props.history?.has_more && (
                                            <p className="text-xs text-muted m-0">
                                                Showing your 30 most recent runs, plus runs started in this browser.
                                            </p>
                                        )}
                                        <p className="text-xs text-muted m-0">
                                            Each row is one scout execution. This history includes older runs and runs
                                            from other comparisons. Select a comparison above to see its grouped judging
                                            report.
                                        </p>
                                    </div>
                                ),
                            },
                        ]}
                    />
                )}
                <ScoutTrialResultModal
                    result={props.selectedResult}
                    report={props.evaluationState.value?.report}
                    onClose={() => props.selectResult(null)}
                />
            </div>
        </div>
    )
}
