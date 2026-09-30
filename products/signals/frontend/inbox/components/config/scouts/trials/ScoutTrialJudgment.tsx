import { LemonBanner, LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type {
    TrialEvaluationCriterionApi,
    TrialRunEvidenceApi,
    TrialRunJudgmentApi,
} from 'products/signals/frontend/generated/api.schemas'

import { trialRunVerdictCounts, trialVerdictLabel } from './scoutTrialPresentation'
import { ScoutTrialVerdictSummary } from './ScoutTrialVerdictSummary'

export function ScoutTrialJudgment({
    judgment,
    evidence,
    criteria,
}: {
    judgment: TrialRunJudgmentApi
    evidence?: TrialRunEvidenceApi
    criteria: TrialEvaluationCriterionApi[]
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3 min-w-0 break-words">
            {evidence && (
                <p className="m-0 text-sm text-muted break-words">{`${evidence.model} · ${evidence.reasoning_effort} effort`}</p>
            )}
            {judgment.status !== 'judged' ? (
                <LemonBanner type={judgment.status === 'judge_error' ? 'error' : 'warning'}>
                    {judgment.error || evidence?.exclusion_reason || judgment.summary}
                </LemonBanner>
            ) : (
                <>
                    <ScoutTrialVerdictSummary counts={trialRunVerdictCounts(judgment.criteria ?? [])} />
                    <p className="m-0">{judgment.summary}</p>
                </>
            )}
            {!!judgment.criteria?.length && (
                <div className="flex min-w-0 flex-col gap-2">
                    <h5 className="m-0 text-sm font-semibold">Rubric checks</h5>
                    <p className="m-0 text-xs text-muted">
                        Open a check to see why it passed or failed and the evidence used.
                    </p>
                    <LemonCollapse
                        multiple
                        size="small"
                        panels={judgment.criteria.map((verdict) => {
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
                                            <strong>Judge's explanation</strong>
                                            <p className="m-0 whitespace-pre-wrap">{verdict.reason}</p>
                                            <span className="text-xs text-muted">{`Judge confidence: ${verdict.confidence}`}</span>
                                        </div>
                                        {!!verdict.evidence?.length && (
                                            <div className="flex flex-col gap-2">
                                                <strong>Supporting evidence</strong>
                                                {verdict.evidence.map((citation, index) => (
                                                    <blockquote
                                                        key={`${citation.source_id}-${index}`}
                                                        className="m-0 border-l-2 pl-3"
                                                    >
                                                        <p className="m-0 whitespace-pre-wrap break-words">
                                                            {citation.quote}
                                                        </p>
                                                        <div className="text-xs text-muted break-all">
                                                            {citation.source_id}
                                                        </div>
                                                    </blockquote>
                                                ))}
                                            </div>
                                        )}
                                        {criterion && (
                                            <div className="flex flex-col gap-1 border-t pt-3 text-secondary">
                                                <strong>What passing looks like</strong>
                                                <p className="m-0">{criterion.pass_condition}</p>
                                                <p className="m-0 text-xs">{`Applies when: ${criterion.applicability}`}</p>
                                            </div>
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
                        {
                            key: 'run-details',
                            header: 'Technical run details',
                            content: (
                                <dl className="m-0 grid grid-cols-1 gap-1 text-xs break-all">
                                    <dt className="font-semibold">Run ID</dt>
                                    <dd className="m-0 mb-2">{judgment.launch_id}</dd>
                                    <dt className="font-semibold">Execution</dt>
                                    <dd className="m-0 mb-2">{`${evidence.runtime_adapter} · ${evidence.execution_status}${evidence.service_tier ? ` · ${evidence.service_tier}` : ''}`}</dd>
                                    <dt className="font-semibold">Prompt fingerprint</dt>
                                    <dd className="m-0">{evidence.skill_body_sha256}</dd>
                                </dl>
                            ),
                        },
                    ]}
                />
            )}
        </div>
    )
}
