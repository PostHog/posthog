import { LemonBanner, LemonCollapse, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type {
    TrialComparisonReportApi,
    TrialVariantAggregateApi,
} from 'products/signals/frontend/generated/api.schemas'

import { ScoutRubricReference } from '../ScoutRubricReference'
import { ScoutTrialJudgment } from './ScoutTrialJudgment'
import { trialPromptLabel, trialRunVerdictCounts, trialVariantVerdictCounts } from './scoutTrialPresentation'
import { trialDelta, trialPercentage } from './scoutTrialUtils'
import { ScoutTrialVerdictSummary } from './ScoutTrialVerdictSummary'

export function ScoutTrialComparisonReport({ report }: { report: TrialComparisonReportApi }): JSX.Element {
    const rubricLabel = report.rubric_source === 'mock' ? 'Mock rubric' : 'Saved rubric'
    const outcome = report.outcome
    const bestVariantNames = report.variants
        .filter((variant) => outcome?.variant_ids?.includes(variant.variant_id))
        .map((variant) => variant.label)
        .join(', ')
    const baselineEvidence = report.evidence.filter((run) => run.variant_id === report.baseline_variant_id)

    return (
        <div className="@container flex flex-col gap-4 min-w-0">
            <LemonBanner
                type={outcome?.status === 'winner' ? 'success' : outcome?.status === 'tie' ? 'info' : 'warning'}
            >
                <div className="flex flex-col gap-1 min-w-0">
                    <strong className="break-words">
                        {outcome?.status === 'winner'
                            ? `Best in these runs: ${bestVariantNames}`
                            : outcome?.status === 'tie'
                              ? `Tie in these runs: ${bestVariantNames}`
                              : 'No clear winner'}
                    </strong>
                    <span className="break-words">
                        {outcome?.summary ??
                            'This saved report has no comparison conclusion. Review the results below or evaluate these runs again.'}
                    </span>
                </div>
            </LemonBanner>

            <div className="flex flex-col gap-2 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                    <h4 className="m-0">Results by variant</h4>
                    <LemonTag type={report.rubric_source === 'mock' ? 'warning' : 'muted'}>{rubricLabel}</LemonTag>
                </div>
                <LemonTable<TrialVariantAggregateApi>
                    dataSource={report.variants}
                    rowKey="variant_id"
                    tableLayout="fixed"
                    size="small"
                    columns={[
                        {
                            title: 'Variant',
                            width: '40%',
                            render: (_, variant) => {
                                const evidence = report.evidence.filter((run) => run.variant_id === variant.variant_id)
                                return (
                                    <div className="flex flex-col items-start gap-1 min-w-0">
                                        <strong className="break-words">{variant.label}</strong>
                                        <div className="flex flex-wrap gap-1">
                                            {variant.is_baseline && <LemonTag type="muted">Baseline</LemonTag>}
                                            {outcome?.variant_ids?.includes(variant.variant_id) && (
                                                <LemonTag type={outcome.status === 'winner' ? 'success' : 'muted'} wrap>
                                                    {outcome.status === 'winner' ? 'Best in these runs' : 'Tied'}
                                                </LemonTag>
                                            )}
                                        </div>
                                        {[
                                            ...new Set(
                                                evidence.map((run) => `${run.model} · ${run.reasoning_effort} effort`)
                                            ),
                                        ].map((setting) => (
                                            <span key={setting} className="text-xs text-muted break-words">
                                                {setting}
                                            </span>
                                        ))}
                                        <span className="text-xs text-muted break-words">
                                            {variant.is_baseline
                                                ? 'Baseline prompt'
                                                : trialPromptLabel(evidence, baselineEvidence)}
                                        </span>
                                        <span className="text-xs">{`${variant.judged_runs} of ${variant.total_runs} runs judged`}</span>
                                        {variant.excluded_runs > 0 && (
                                            <span className="text-xs text-warning">{`${pluralize(variant.excluded_runs, 'run')} not scored`}</span>
                                        )}
                                        {variant.judge_errors > 0 && (
                                            <span className="text-xs text-danger">{`${pluralize(variant.judge_errors, 'run')} could not be judged`}</span>
                                        )}
                                    </div>
                                )
                            },
                        },
                        {
                            title: <span className="whitespace-normal">Average pass rate</span>,
                            width: '25%',
                            render: (_, variant) => (
                                <div className="flex flex-col gap-1 break-words">
                                    <strong>{trialPercentage(variant.score)}</strong>
                                    {!variant.is_baseline && (
                                        <span className="text-xs text-muted">
                                            {variant.baseline_delta == null
                                                ? 'Not comparable with baseline'
                                                : `${trialDelta(variant.baseline_delta)} vs baseline`}
                                        </span>
                                    )}
                                </div>
                            ),
                        },
                        {
                            title: 'Rubric checks',
                            width: '35%',
                            render: (_, variant) => (
                                <ScoutTrialVerdictSummary counts={trialVariantVerdictCounts(variant.criteria)} />
                            ),
                        },
                    ]}
                />
                <p className="m-0 text-xs text-muted">
                    Check counts include every judged run. The pass rate is averaged across runs; checks without enough
                    evidence and checks that do not apply are left out of that rate. Results describe these runs, not
                    future performance.
                </p>
            </div>

            <div className="flex flex-col gap-3 min-w-0">
                <h4 className="m-0">Individual runs</h4>
                <p className="m-0 text-sm text-muted">
                    Each row is one execution of a variant. Open a run, then a rubric check, to inspect the judge's
                    explanation.
                </p>
                {report.variants.map((variant) => {
                    const runs = report.runs.filter((run) => run.variant_id === variant.variant_id)
                    return (
                        <div key={variant.variant_id} className="flex flex-col gap-2 min-w-0">
                            <h5 className="m-0 text-sm font-semibold break-words">{variant.label}</h5>
                            <LemonCollapse
                                multiple
                                size="small"
                                panels={runs.map((run, runIndex) => ({
                                    key: run.launch_id,
                                    header: (
                                        <div className="flex flex-1 min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 text-left">
                                            <span className="shrink-0">{`Run ${runIndex + 1} of ${runs.length}`}</span>
                                            {run.status === 'judged' ? (
                                                <ScoutTrialVerdictSummary
                                                    counts={trialRunVerdictCounts(run.criteria ?? [])}
                                                />
                                            ) : (
                                                <LemonTag
                                                    type={run.status === 'judge_error' ? 'danger' : 'warning'}
                                                    wrap
                                                >
                                                    {run.status === 'judge_error'
                                                        ? 'Could not be judged'
                                                        : 'Not scored'}
                                                </LemonTag>
                                            )}
                                        </div>
                                    ),
                                    content: (
                                        <ScoutTrialJudgment
                                            judgment={run}
                                            evidence={report.evidence.find((item) => item.launch_id === run.launch_id)}
                                            criteria={report.criteria}
                                        />
                                    ),
                                }))}
                            />
                        </div>
                    )
                })}
            </div>

            <div className="flex flex-col gap-2 min-w-0">
                <h4 className="m-0">About this evaluation</h4>
                <LemonCollapse
                    multiple
                    size="small"
                    panels={[
                        {
                            key: 'rubric',
                            header: `${rubricLabel}: ${pluralize(report.criteria.length, 'check')} · revision ${report.rubric_revision}`,
                            content: (
                                <LemonCollapse
                                    multiple
                                    embedded
                                    size="small"
                                    panels={report.criteria.map((criterion) => ({
                                        key: criterion.id,
                                        header: <span className="break-words">{criterion.title}</span>,
                                        content: (
                                            <div className="flex flex-col gap-2 text-sm break-words">
                                                <p className="m-0">{criterion.description}</p>
                                                <div>
                                                    <strong>What passing looks like</strong>
                                                    <p className="m-0">{criterion.pass_condition}</p>
                                                </div>
                                                <p className="m-0 text-muted">{`Applies when: ${criterion.applicability}`}</p>
                                            </div>
                                        ),
                                    }))}
                                />
                            ),
                        },
                        !!report.rubric_reference_context && {
                            key: 'rubric-reference',
                            header: 'Scout reference saved with this rubric',
                            content: <ScoutRubricReference reference={report.rubric_reference_context!} />,
                        },
                        !!report.limitations.length && {
                            key: 'limitations',
                            header: 'How to interpret these results',
                            content: (
                                <ul className="m-0 pl-4 text-sm flex flex-col gap-2">
                                    {report.limitations.map((limitation) => (
                                        <li key={limitation}>{limitation}</li>
                                    ))}
                                </ul>
                            ),
                        },
                        {
                            key: 'evaluation-details',
                            header: 'Technical evaluation details',
                            content: (
                                <dl className="m-0 grid grid-cols-1 gap-1 text-xs break-all">
                                    <dt className="font-semibold">Judge model</dt>
                                    <dd className="m-0 mb-2">{report.judge_model}</dd>
                                    <dt className="font-semibold">Judge prompt version</dt>
                                    <dd className="m-0 mb-2">{report.judge_prompt_version}</dd>
                                    <dt className="font-semibold">Evaluation ID</dt>
                                    <dd className="m-0">{report.evaluation_id}</dd>
                                </dl>
                            ),
                        },
                    ]}
                />
            </div>
        </div>
    )
}
