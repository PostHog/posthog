import { LemonBanner, LemonCollapse, LemonTable, LemonTag } from '@posthog/lemon-ui'

import type {
    TrialComparisonReportApi,
    TrialVariantAggregateApi,
} from 'products/signals/frontend/generated/api.schemas'

import { ScoutTrialJudgment } from './ScoutTrialJudgment'
import { trialDelta, trialPercentage } from './scoutTrialUtils'

export function ScoutTrialComparisonReport({ report }: { report: TrialComparisonReportApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-3 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
                <h4 className="m-0">Comparison report</h4>
                <LemonTag type="warning">Mock rubric</LemonTag>
            </div>
            <p className="m-0 text-sm break-words">{report.summary}</p>
            <p className="m-0 text-xs text-muted">
                Scores average each repeat's pass rate among pass/fail verdicts. Coverage shows how much applicable
                evidence could be judged. Unknown verdicts and excluded runs do not count as failures. Differences
                describe this sample; they are not statistical significance tests.
            </p>
            <LemonTable<TrialVariantAggregateApi>
                dataSource={report.variants}
                rowKey="variant_id"
                tableLayout="fixed"
                size="small"
                columns={[
                    {
                        title: 'Variant / repeats',
                        width: '44%',
                        render: (_, variant) => (
                            <div className="flex flex-col items-start gap-1 min-w-0">
                                <strong className="break-words">{variant.label}</strong>
                                {variant.is_baseline && <LemonTag type="muted">Baseline</LemonTag>}
                                <span className="text-xs text-muted">{`${variant.judged_runs}/${variant.total_runs} runs judged`}</span>
                                {(variant.excluded_runs > 0 || variant.judge_errors > 0) && (
                                    <span className="text-xs text-muted">{`${variant.excluded_runs} excluded · ${variant.judge_errors} judge errors`}</span>
                                )}
                            </div>
                        ),
                    },
                    {
                        title: 'Score',
                        width: '28%',
                        render: (_, variant) => (
                            <div className="flex flex-col gap-1 break-words">
                                <strong>{trialPercentage(variant.score)}</strong>
                                {!variant.is_baseline && (
                                    <span className="text-xs text-muted">
                                        {trialDelta(variant.baseline_delta ?? null)}
                                    </span>
                                )}
                            </div>
                        ),
                    },
                    { title: 'Coverage', width: '28%', render: (_, variant) => trialPercentage(variant.coverage) },
                ]}
            />
            {!!report.limitations.length && (
                <LemonBanner type="warning">
                    <ul className="m-0 pl-4">
                        {report.limitations.map((limitation) => (
                            <li key={limitation}>{limitation}</li>
                        ))}
                    </ul>
                </LemonBanner>
            )}
            <LemonCollapse
                multiple
                panels={[
                    {
                        key: 'rubric',
                        header: `Mock rubric · revision ${report.rubric_revision}`,
                        content: (
                            <div className="flex flex-col gap-4">
                                {report.criteria.map((criterion) => (
                                    <div key={criterion.id} className="flex flex-col gap-1 text-sm break-words">
                                        <strong>{criterion.title}</strong>
                                        <p className="m-0">{criterion.description}</p>
                                        <p className="m-0">{`Pass: ${criterion.pass_condition}`}</p>
                                        <p className="m-0 text-muted">{`Applies when: ${criterion.applicability}`}</p>
                                        {report.variants.map((variant) => {
                                            const aggregate = variant.criteria.find(
                                                (item) => item.criterion_id === criterion.id
                                            )
                                            return aggregate ? (
                                                <div key={variant.variant_id} className="text-xs text-muted">
                                                    {`${variant.label}: ${aggregate.passed} pass, ${aggregate.failed} fail, ${aggregate.unknown} unknown, ${aggregate.not_applicable} not applicable · ${trialPercentage(aggregate.coverage)} coverage`}
                                                </div>
                                            ) : null
                                        })}
                                    </div>
                                ))}
                            </div>
                        ),
                    },
                    ...report.runs.map((run, runIndex) => ({
                        key: run.launch_id,
                        header: (
                            <span className="break-words">
                                {`${report.variants.find((variant) => variant.variant_id === run.variant_id)?.label ?? 'Run'} · repeat ${report.runs.slice(0, runIndex).filter((item) => item.variant_id === run.variant_id).length + 1} · ${run.status === 'judged' ? trialPercentage(run.score ?? null) : run.status.replaceAll('_', ' ')}`}
                            </span>
                        ),
                        content: (
                            <ScoutTrialJudgment
                                judgment={run}
                                evidence={report.evidence.find((item) => item.launch_id === run.launch_id)}
                                criteria={report.criteria}
                            />
                        ),
                    })),
                ]}
            />
            <p className="m-0 text-xs text-muted break-all">{`Judge: ${report.judge_model} · prompt ${report.judge_prompt_version} · evaluation ${report.evaluation_id}`}</p>
        </div>
    )
}
