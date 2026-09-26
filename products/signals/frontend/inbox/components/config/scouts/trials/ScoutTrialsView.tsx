import { IconDownload, IconPlus, IconRefresh } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
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
import { ScoutTrialComparisonReport } from './ScoutTrialComparisonReport'
import { ScoutTrialResultModal } from './ScoutTrialResultModal'
import { MAX_TRIAL_RUNS, ScoutTrialRow, trialIsActive } from './scoutTrialUtils'
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
    const finishedSubmissions = !!batch && !props.hasUnaccepted && !submitting
    const runCountLabel = `${totalRuns} ${totalRuns === 1 ? 'run' : 'runs'}`

    return (
        <div className="@container flex flex-1 min-h-0 min-w-0 flex-col overflow-auto ph-no-capture ph-replay-block">
            <div className="p-4 flex flex-col gap-4 max-w-5xl w-full mx-auto">
                <div className="flex flex-wrap items-center gap-2">
                    <h2 className="m-0 text-lg font-semibold">Scout comparisons</h2>
                    <LemonTag type="muted">Internal</LemonTag>
                </div>
                <p className="m-0 text-sm text-muted">
                    Compare prompts, models, and effort against live project data. Each run starts with the same saved
                    history and keeps its new reports and memory private.
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
                {currentSetup?.ready && (
                    <>
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
                            {!finishedSubmissions && (
                                <LemonButton
                                    type="primary"
                                    onClick={props.submitComparison}
                                    loading={submitting}
                                    disabledReason={batch ? undefined : props.formError}
                                    data-attr="scout-comparison-start"
                                >
                                    {batch ? 'Retry unconfirmed submissions' : `Start ${runCountLabel}`}
                                </LemonButton>
                            )}
                            {batch && (
                                <LemonButton
                                    type="secondary"
                                    onClick={props.newComparison}
                                    disabledReason={submitting ? 'Wait for all submissions to finish.' : undefined}
                                >
                                    New comparison
                                </LemonButton>
                            )}
                        </div>
                        {submitting ? (
                            <LemonBanner type="info">
                                Submitting runs. Keep this page open until all submissions are confirmed.
                            </LemonBanner>
                        ) : finishedSubmissions ? (
                            <LemonBanner type="success">
                                All runs were accepted. They continue if you close this page.
                            </LemonBanner>
                        ) : batch && props.hasUnaccepted ? (
                            <LemonBanner type="warning">
                                Some submissions were not confirmed. Retry here to reuse their IDs without duplicating
                                accepted runs.
                            </LemonBanner>
                        ) : (
                            <p className="m-0 text-xs text-muted">
                                Runs use live data, which can change during a comparison. Model charges apply; dollar
                                costs may be unavailable.
                            </p>
                        )}
                    </>
                )}

                {selectedConfigId && (
                    <div className="flex flex-col gap-3 border-t pt-4">
                        <div className="flex flex-wrap items-center gap-2">
                            <h3 className="m-0 text-base">Score a comparison</h3>
                            <LemonTag type="warning">Mock rubric</LemonTag>
                        </div>
                        <p className="m-0 text-sm text-muted">
                            A model judges the selected comparison against a fixed mock rubric. This is an early
                            evaluation signal, not a production quality gate. Scoring incurs additional model charges.
                        </p>
                        {props.selectedComparison ? (
                            <>
                                <LemonField.Pure label="Comparison">
                                    <LemonSelect
                                        value={props.selectedComparison.id}
                                        options={props.comparisonsForConfig.map((comparison) => ({
                                            value: comparison.id,
                                            label: `${comparison.id.slice(0, 8)} · ${comparison.groups.length} variants · ${comparison.groups.reduce((count, group) => count + group.launchIds.length, 0)} runs`,
                                        }))}
                                        onChange={(id) => props.selectComparison(selectedConfigId, id!)}
                                        fullWidth
                                        menu={{ className: 'ph-no-capture ph-replay-block' }}
                                    />
                                </LemonField.Pure>
                                <div className="flex flex-wrap gap-2">
                                    <LemonButton
                                        type="primary"
                                        onClick={props.scoreComparison}
                                        loading={props.evaluationState.scoring}
                                        disabledReason={props.scoreDisabledReason}
                                    >
                                        {props.evaluationState.value?.status === 'failed'
                                            ? 'Retry scoring'
                                            : 'Score comparison'}
                                    </LemonButton>
                                    <LemonButton
                                        type="secondary"
                                        icon={<IconRefresh />}
                                        loading={props.evaluationState.loading}
                                        disabledReason={
                                            props.evaluationState.scoring
                                                ? 'Wait for scoring to be submitted.'
                                                : undefined
                                        }
                                        onClick={() => props.loadEvaluation(props.selectedComparison!.id)}
                                    >
                                        Refresh scoring
                                    </LemonButton>
                                    {props.evaluationState.value?.report && (
                                        <LemonButton
                                            type="secondary"
                                            icon={<IconDownload />}
                                            onClick={props.downloadEvaluation}
                                        >
                                            Download report
                                        </LemonButton>
                                    )}
                                    {props.evaluationState.value?.report?.variants.some(
                                        (variant) => variant.judge_errors > 0
                                    ) && (
                                        <LemonButton
                                            type="secondary"
                                            onClick={props.newScoringAttempt}
                                            disabledReason={
                                                props.evaluationState.loading || props.evaluationState.scoring
                                                    ? 'Wait for scoring status to load.'
                                                    : undefined
                                            }
                                        >
                                            New scoring attempt
                                        </LemonButton>
                                    )}
                                </div>
                                {props.evaluationState.value?.report?.variants.some(
                                    (variant) => variant.judge_errors > 0
                                ) && (
                                    <p className="m-0 text-xs text-muted">
                                        Prepare another evaluation of these same runs to retry judge errors. The
                                        previous report stays available. You choose when to score; a new attempt may
                                        charge for all runs again.
                                    </p>
                                )}
                                {props.evaluationState.error && (
                                    <LemonBanner type="error">{props.evaluationState.error}</LemonBanner>
                                )}
                                {props.evaluationState.value?.error && (
                                    <LemonBanner type="error">{props.evaluationState.value.error}</LemonBanner>
                                )}
                                {(props.evaluationState.value?.status === 'pending' ||
                                    props.evaluationState.value?.status === 'running') && (
                                    <LemonBanner type="info">
                                        Scoring is in progress. The saved report will appear here when it is ready.
                                    </LemonBanner>
                                )}
                                {props.evaluationState.value?.status === 'unknown' && (
                                    <LemonBanner type="warning">
                                        Scoring status is unavailable. Refresh before retrying to avoid starting a
                                        duplicate evaluation.
                                    </LemonBanner>
                                )}
                                {props.evaluationState.value?.report && (
                                    <ScoutTrialComparisonReport report={props.evaluationState.value.report} />
                                )}
                            </>
                        ) : (
                            <LemonBanner type="info">
                                Start a comparison above to keep its variant groups together for scoring. Older
                                ungrouped runs remain available below.
                            </LemonBanner>
                        )}
                    </div>
                )}

                {selectedConfigId && (
                    <div className="flex flex-col gap-3 border-t pt-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h3 className="m-0 text-base">Your recent runs</h3>
                            <div className="flex flex-wrap gap-2">
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    icon={<IconRefresh />}
                                    loading={props.refreshing || props.historyLoading}
                                    onClick={() => {
                                        props.refreshResults(true)
                                        props.loadHistory(selectedConfigId)
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
                                        !rows.some((row) => row.result) ? 'No results have loaded yet.' : undefined
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
                                                {row.model ? `${row.model} · ${row.effort}` : row.launchId}
                                            </div>
                                            {row.startedAt && (
                                                <div className="text-xs text-muted">
                                                    {dayjs(row.startedAt).format('MMM D, HH:mm')}
                                                </div>
                                            )}
                                            {row.error && (
                                                <div className="text-xs text-danger break-words">{row.error}</div>
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
                                                        : row.status === 'failed' || row.status === 'submission_failed'
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
                                                    !row.result ? 'Results have not loaded yet.' : undefined
                                                }
                                            >
                                                Results
                                            </LemonButton>
                                            {row.result?.task_id &&
                                                row.result.task_run_id &&
                                                (trialIsActive(row.status) ||
                                                    trialIsActive(row.result.task_status ?? '')) && (
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
                            Accepted runs can be reopened after a refresh. Unsubmitted prompts are not saved in your
                            browser; start a new comparison if you left during submission.
                        </p>
                    </div>
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
