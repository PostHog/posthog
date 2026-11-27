import { LemonTag } from 'lib/lemon-ui/LemonTag'

import type { AnomalyJudgeKindEnumApi } from 'products/signals/frontend/generated/api.schemas'

import type { AnomalyVerdict } from './anomalyChartData'

const KIND_LABELS: Record<AnomalyJudgeKindEnumApi, string> = {
    spike: 'Spike',
    drop: 'Drop',
    flatline: 'Flatline',
    trend_break: 'Trend break',
    level_shift: 'Level shift',
    pattern_change: 'Pattern change',
}

/** Why the AI judge confirmed a flagged bucket, for a chart tooltip. The reason is model output, so it stays plain text. */
export function AnomalyJudgeVerdict({ verdict }: { verdict: AnomalyVerdict }): JSX.Element {
    const kindLabel = verdict.anomaly_kind ? KIND_LABELS[verdict.anomaly_kind] : undefined
    return (
        <div className="flex flex-col items-start gap-1 text-left" data-attr="anomaly-judge-verdict">
            {kindLabel && <LemonTag size="small">{kindLabel}</LemonTag>}
            <p className="m-0 whitespace-pre-line">{verdict.anomaly_reason}</p>
            <span>Reason written by AI</span>
        </div>
    )
}
