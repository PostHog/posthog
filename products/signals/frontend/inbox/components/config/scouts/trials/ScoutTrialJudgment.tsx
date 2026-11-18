import { LemonBanner, LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type {
    TrialEvaluationCriterionApi,
    TrialRunEvidenceApi,
    TrialRunJudgmentApi,
} from 'products/signals/frontend/generated/api.schemas'

import { trialOrderedVerdicts, trialRunVerdictCounts, trialVerdictLabel } from './scoutTrialPresentation'

export function ScoutTrialJudgment({
    judgment,
    evidence,
    criteria,
    summary,
}: {
    judgment: TrialRunJudgmentApi
    evidence?: TrialRunEvidenceApi
    criteria: TrialEvaluationCriterionApi[]
    summary?: string
}): JSX.Element {
    const counts = trialRunVerdictCounts(judgment.criteria ?? [])
    return (
        <div className="flex flex-col gap-3 min-w-0 break-words">
            {judgment.status !== 'judged' ? (
                <LemonBanner type={judgment.status === 'judge_error' ? 'error' : 'warning'}>
                    {judgment.error || evidence?.exclusion_reason || judgment.summary}
                </LemonBanner>
            ) : (
                <>
                    <div className="flex flex-wrap gap-2">
                        <LemonTag type="success">{`${counts.passed} passed`}</LemonTag>
                        <LemonTag type={counts.failed ? 'danger' : 'muted'}>{`${counts.failed} failed`}</LemonTag>
                        <LemonTag type={counts.unknown ? 'warning' : 'muted'}>{`${counts.unknown} unknown`}</LemonTag>
                        {counts.not_applicable > 0 && (
                            <LemonTag type="muted">{`${counts.not_applicable} not applicable`}</LemonTag>
                        )}
                    </div>
                    <p className="m-0 whitespace-pre-wrap">{summary || judgment.summary}</p>
                </>
            )}
            {!!judgment.criteria?.length && (
                <div className="flex min-w-0 flex-col gap-2">
                    <h5 className="m-0 text-sm font-semibold">Rubric checks</h5>
                    <p className="m-0 text-xs text-muted">
                        Failed and unknown first. Open a check to see the judge's reasoning.
                    </p>
                    <LemonCollapse
                        multiple
                        size="small"
                        panels={trialOrderedVerdicts(judgment.criteria, criteria).map((verdict) => {
                            const criterion = criteria.find((item) => item.id === verdict.criterion_id)
                            return {
                                key: verdict.criterion_id,
                                header: (
                                    <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-2 text-left">
                                        <span className="min-w-0 flex-1 break-words">
                                            {criterion?.title ?? verdict.criterion_id}
                                        </span>
                                        <LemonTag
                                            type={
                                                verdict.verdict === 'pass'
                                                    ? 'success'
                                                    : verdict.verdict === 'fail'
                                                      ? 'danger'
                                                      : verdict.verdict === 'unknown'
                                                        ? 'warning'
                                                        : 'muted'
                                            }
                                            wrap
                                        >
                                            {trialVerdictLabel(verdict.verdict)}
                                        </LemonTag>
                                    </div>
                                ),
                                content: (
                                    <div className="flex min-w-0 flex-col gap-3 text-sm">
                                        <div className="flex flex-col gap-1">
                                            <strong>Judge's reasoning</strong>
                                            <p className="m-0 whitespace-pre-wrap">{verdict.reason}</p>
                                            <span className="text-xs text-muted">{`Confidence: ${verdict.confidence}`}</span>
                                        </div>
                                        {!!verdict.evidence?.length && (
                                            <div className="flex flex-col gap-2">
                                                <strong>Evidence</strong>
                                                {verdict.evidence.map((citation, index) => (
                                                    <blockquote
                                                        key={`${citation.source_id}-${index}`}
                                                        className="m-0 border-l-2 pl-3"
                                                    >
                                                        <p className="m-0 whitespace-pre-wrap break-words">
                                                            {citation.quote}
                                                        </p>
                                                        <div className="font-mono text-xs text-muted break-all">
                                                            {citation.source_id}
                                                        </div>
                                                    </blockquote>
                                                ))}
                                            </div>
                                        )}
                                        {criterion && (
                                            <dl className="m-0 grid grid-cols-1 gap-x-3 gap-y-1 rounded border bg-surface-secondary p-3 @sm:grid-cols-[5.5rem_minmax(0,1fr)]">
                                                <dt className="font-semibold">Passes when</dt>
                                                <dd className="m-0">{criterion.pass_condition}</dd>
                                                <dt className="font-semibold">Applies to</dt>
                                                <dd className="m-0">{criterion.applicability}</dd>
                                            </dl>
                                        )}
                                    </div>
                                ),
                            }
                        })}
                    />
                </div>
            )}
            {!!evidence?.limitations?.length && (
                <LemonBanner type="warning">
                    <ul className="m-0 pl-4">
                        {evidence.limitations.map((limitation) => (
                            <li key={limitation}>{limitation}</li>
                        ))}
                    </ul>
                </LemonBanner>
            )}
            {evidence && (
                <LemonCollapse
                    multiple
                    size="small"
                    panels={[
                        !!evidence.sources?.length && {
                            key: 'captured-evidence',
                            header: `All captured evidence (${pluralize(evidence.sources.length, 'source')})`,
                            content: (
                                <LemonCollapse
                                    multiple
                                    embedded
                                    size="small"
                                    panels={evidence.sources.map((source) => ({
                                        key: source.id,
                                        header: <span className="break-all">{`${source.kind}: ${source.id}`}</span>,
                                        content: (
                                            <pre className="m-0 text-xs whitespace-pre-wrap break-words">
                                                {source.text}
                                            </pre>
                                        ),
                                    }))}
                                />
                            ),
                        },
                    ]}
                />
            )}
        </div>
    )
}
