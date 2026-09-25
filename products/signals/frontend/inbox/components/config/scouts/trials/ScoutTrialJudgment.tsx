import { LemonBanner, LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import type {
    TrialEvaluationCriterionApi,
    TrialRunEvidenceApi,
    TrialRunJudgmentApi,
} from 'products/signals/frontend/generated/api.schemas'

import { trialPercentage } from './scoutTrialUtils'

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
                <p className="m-0 text-xs text-muted break-all">{`${evidence.model} · ${evidence.reasoning_effort} effort · ${evidence.runtime_adapter}${evidence.service_tier ? ` · ${evidence.service_tier}` : ''} · ${evidence.execution_status}`}</p>
            )}
            {judgment.status !== 'judged' ? (
                <LemonBanner type={judgment.status === 'judge_error' ? 'error' : 'warning'}>
                    {judgment.error || evidence?.exclusion_reason || judgment.summary}
                </LemonBanner>
            ) : (
                <>
                    <div className="flex flex-wrap gap-3 text-sm">
                        <strong>{`Score ${trialPercentage(judgment.score ?? null)}`}</strong>
                        <span>{`Evidence coverage ${trialPercentage(judgment.coverage ?? null)}`}</span>
                    </div>
                    <p className="m-0">{judgment.summary}</p>
                </>
            )}
            {(judgment.criteria ?? []).map((verdict) => (
                <div key={verdict.criterion_id} className="border rounded p-3 flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <strong>
                            {criteria.find((criterion) => criterion.id === verdict.criterion_id)?.title ??
                                verdict.criterion_id}
                        </strong>
                        <LemonTag
                            type={
                                verdict.verdict === 'pass' ? 'success' : verdict.verdict === 'fail' ? 'danger' : 'muted'
                            }
                            wrap
                        >
                            {verdict.verdict.replaceAll('_', ' ')}
                        </LemonTag>
                        <span className="text-xs text-muted">{`${verdict.confidence} confidence`}</span>
                    </div>
                    <p className="m-0 text-sm">{verdict.reason}</p>
                    {(verdict.evidence ?? []).map((citation, index) => (
                        <blockquote key={`${citation.source_id}-${index}`} className="m-0 border-l-2 pl-3">
                            <p className="m-0 whitespace-pre-wrap text-sm">{citation.quote}</p>
                            <div className="text-xs text-muted break-all">{citation.source_id}</div>
                        </blockquote>
                    ))}
                </div>
            ))}
            {!!evidence?.limitations?.length && (
                <LemonBanner type="warning">
                    <ul className="m-0 pl-4">
                        {evidence.limitations.map((limitation) => (
                            <li key={limitation}>{limitation}</li>
                        ))}
                    </ul>
                </LemonBanner>
            )}
            {!!evidence?.sources?.length && (
                <LemonCollapse
                    multiple
                    panels={evidence.sources.map((source) => ({
                        key: source.id,
                        header: <span className="break-all">{`${source.kind}: ${source.id}`}</span>,
                        content: <pre className="m-0 text-xs whitespace-pre-wrap break-words">{source.text}</pre>,
                    }))}
                />
            )}
        </div>
    )
}
