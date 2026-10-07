import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import type { MetricsQuery, MetricsQueryLanguage } from '~/queries/schema/schema-general'

import { convertMetricsQuery, queryLanguage } from '../queryLanguages/convert'

export const METRICS_QUERY_LANGUAGE_LABELS: Record<MetricsQueryLanguage, string> = {
    builder: 'Builder',
    promql: 'PromQL',
    sql: 'SQL',
}

/** Converts a metrics query to another language. When the conversion loses something, it asks first. */
export function switchMetricsQueryLanguage(
    query: MetricsQuery,
    to: MetricsQueryLanguage,
    apply: (query: MetricsQuery) => void
): void {
    const from = queryLanguage(query)
    if (from === to) {
        return
    }
    const { query: converted, issues } = convertMetricsQuery(query, to)
    const track = (confirmed: boolean): void => {
        posthog.capture('metrics query language switched', {
            from,
            to,
            lossy: issues.length > 0,
            issue_count: issues.length,
            confirmed,
        })
    }
    if (!issues.length) {
        track(true)
        apply(converted)
        return
    }
    const label = METRICS_QUERY_LANGUAGE_LABELS[to]
    LemonDialog.open({
        title: `Switch to ${label}?`,
        description: (
            <div className="flex flex-col gap-2">
                <p>Some parts of this query do not convert exactly:</p>
                <ul className="list-disc pl-5 flex flex-col gap-1">
                    {issues.map((issue) => (
                        <li key={issue}>{issue}</li>
                    ))}
                </ul>
                <p>Switching back does not bring these parts back.</p>
            </div>
        ),
        primaryButton: {
            children: `Switch to ${label}`,
            onClick: () => {
                track(true)
                apply(converted)
            },
        },
        secondaryButton: { children: 'Cancel', onClick: () => track(false) },
    })
}
