import api from 'lib/api'

import { type HogQLQueryString, hogql } from '~/queries/utils'

/** Ingestion writes per-rule drops to app_metrics2; HogQL exposes it as `app_metrics`. */
export async function fetchSamplingRuleDropTotalsLast24h(ruleIds: string[]): Promise<Record<string, number>> {
    if (ruleIds.length === 0) {
        return {}
    }
    const query = hogql`
        SELECT instance_id, sum(count) AS dropped
        FROM app_metrics
        WHERE app_source = ${'logs'}
          AND metric_name = ${'sampling_records_dropped_by_rule'}
          AND instance_id IN ${ruleIds}
          AND timestamp >= now() - INTERVAL 24 HOUR
        GROUP BY instance_id
    ` as HogQLQueryString

    const response = await api.queryHogQL(query, {
        scene: 'logs_sampling',
        productKey: 'logs',
        name: 'sampling_rule_drop_totals_24h',
    })

    const out: Record<string, number> = {}
    for (const row of response.results ?? []) {
        const instanceId = String(row[0] ?? '')
        if (!instanceId) {
            continue
        }
        out[instanceId] = Number(row[1] ?? 0)
    }
    return out
}
