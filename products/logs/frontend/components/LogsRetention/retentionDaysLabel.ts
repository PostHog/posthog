import { LogsRetentionRuleApi } from 'products/logs/frontend/generated/api.schemas'

import { logsRetentionDaysLabel } from './logsRetentionPeriod'

/** Read the retention tier out of the rule's config JSON for display. */
export function retentionDaysLabel(rule: LogsRetentionRuleApi): string {
    const days = (rule.config as Record<string, unknown> | undefined)?.retention_days
    return typeof days === 'number' ? logsRetentionDaysLabel(days) : '—'
}
