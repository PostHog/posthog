import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { saveSpanMetricLogic } from './saveSpanMetricLogic'
import type { SpanMetricRuleDraft } from './spanMetricRuleDraft'

const OPERATOR_LABELS: Record<string, string> = { exact: '=', is_not: '!=', regex: '=~', not_regex: '!~' }

function whatItRecords(draft: SpanMetricRuleDraft): string {
    if (draft.rule.value_attribute === 'duration_ms') {
        return 'Records the duration of each matching span in milliseconds, as a distribution.'
    }
    return 'Counts matching spans.'
}

export function SaveSpanMetricModal(): JSX.Element | null {
    const { draft, metricName, metricNameError, submitting } = useValues(saveSpanMetricLogic)
    const { closeSaveSpanMetric, setMetricName, submitSpanMetric } = useActions(saveSpanMetricLogic)

    if (!draft) {
        return null
    }
    const filters = draft.filters
    const dropped = [...draft.droppedFilters, ...draft.droppedGroupByKeys]

    return (
        <LemonModal
            isOpen
            onClose={closeSaveSpanMetric}
            title="Save as metric"
            description="Creates a metric from incoming spans. It counts spans from now on, so it starts empty and doesn't include spans from before you save."
            width={560}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeSaveSpanMetric}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitSpanMetric}
                        loading={submitting}
                        disabledReason={metricNameError ?? undefined}
                        data-attr="metrics-save-span-metric-submit"
                    >
                        Create metric
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <label className="font-semibold" htmlFor="save-span-metric-name">
                        Metric name
                    </label>
                    <LemonInput
                        id="save-span-metric-name"
                        value={metricName}
                        onChange={setMetricName}
                        status={metricName && metricNameError ? 'danger' : 'default'}
                        autoFocus
                    />
                    {metricName && metricNameError ? <span className="text-danger">{metricNameError}</span> : null}
                </div>
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">What it records</span>
                    <span>{whatItRecords(draft)}</span>
                    <ul className="list-disc pl-5">
                        {filters.map((filter) => (
                            <li key={`${filter.key}-${filter.operator}-${filter.value}`} className="font-mono">
                                {filter.key} {OPERATOR_LABELS[filter.operator] ?? filter.operator} {filter.value}
                            </li>
                        ))}
                    </ul>
                    {draft.rule.group_by?.length ? (
                        <span>
                            One series per <span className="font-mono">{draft.rule.group_by.join(', ')}</span>
                        </span>
                    ) : null}
                </div>
                {draft.addsServerFilter ? (
                    <LemonBanner type="info">
                        Only server spans count (kind 2). The chart also counts root spans for services that have no
                        server spans, so for those services the saved metric can be lower.
                    </LemonBanner>
                ) : null}
                {draft.ignoresCase ? (
                    <LemonBanner type="info">
                        The saved metric matches filter values without regard to case, so <code>API</code> and{' '}
                        <code>api</code> count together.
                    </LemonBanner>
                ) : null}
                {dropped.length ? (
                    <LemonBanner type="warning">
                        <div>The saved metric can't carry over these parts of the query, so it leaves them out:</div>
                        <ul className="list-disc pl-5 font-mono">
                            {dropped.map((item) => (
                                <li key={item}>{item}</li>
                            ))}
                        </ul>
                    </LemonBanner>
                ) : null}
            </div>
        </LemonModal>
    )
}
