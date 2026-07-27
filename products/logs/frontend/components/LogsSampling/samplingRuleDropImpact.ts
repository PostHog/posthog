import api from 'lib/api'

import { type HogQLQueryString, hogql } from '~/queries/utils'

export interface SamplingRuleDropTotals {
    records: number
    bytes: number
}

/**
 * Ingestion writes per-rule drops to app_metrics2; HogQL exposes it as `app_metrics`.
 * Records are always populated (counted since the original metrics PR); bytes are
 * populated for any drop that ran through a producer carrying per-row `bytes_uncompressed`
 * (i.e. since the bytes-by-row producer change rolled out). Older drops attribute 0 bytes.
 */
export async function fetchSamplingRuleDropTotalsLast24h(
    ruleIds: string[]
): Promise<Record<string, SamplingRuleDropTotals>> {
    if (ruleIds.length === 0) {
        return {}
    }
    const query = hogql`
        SELECT
            instance_id,
            metric_name,
            sum(count) AS total
        FROM app_metrics
        WHERE app_source = ${'logs'}
          AND metric_name IN (${'sampling_records_dropped_by_rule'}, ${'bytes_dropped_by_rule'})
          AND instance_id IN ${ruleIds}
          AND timestamp >= now() - INTERVAL 24 HOUR
        GROUP BY instance_id, metric_name
    ` as HogQLQueryString

    const response = await api.queryHogQL(query, {
        scene: 'logs_sampling',
        productKey: 'logs',
        name: 'sampling_rule_drop_totals_24h',
    })

    const out: Record<string, SamplingRuleDropTotals> = {}
    for (const row of response.results ?? []) {
        const instanceId = String(row[0] ?? '')
        const metricName = String(row[1] ?? '')
        const total = Number(row[2] ?? 0)
        if (!instanceId) {
            continue
        }
        const existing = out[instanceId] ?? { records: 0, bytes: 0 }
        if (metricName === 'sampling_records_dropped_by_rule') {
            existing.records = total
        } else if (metricName === 'bytes_dropped_by_rule') {
            existing.bytes = total
        }
        out[instanceId] = existing
    }
    return out
}
