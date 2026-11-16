import { router } from 'kea-router'

import type { EmailDeliveryStatusEnumApi } from 'products/messaging/frontend/generated/api.schemas'

import type { EmailMetricName } from '../../Workflows/workflowMetricsSummaryLogic'
import { logWindow } from './transactionalEmailLogLogic'

// pinned: values of the log's `reason` filter - kept in sync with EmailStatusReason in nodejs/src/cdp/services/messaging/email-status.service.ts
const EMAIL_METRIC_SENDS: Partial<Record<EmailMetricName, { status: EmailDeliveryStatusEnumApi; reason?: string }>> = {
    email_bounced: { status: 'bounced' },
    email_bounced_hard: { status: 'bounced', reason: 'hard' },
    email_bounced_transient: { status: 'bounced', reason: 'soft' },
    email_bounced_undetermined: { status: 'bounced', reason: 'unknown' },
    email_blocked: { status: 'complained' },
    email_bounce_prevented: { status: 'failed', reason: 'recipient_unreachable' },
    email_missing_recipient: { status: 'failed', reason: 'missing_recipient' },
    message_frequency_capped: { status: 'failed', reason: 'frequency_capped' },
    email_suspended: { status: 'failed', reason: 'sending_suspended' },
    email_paused: { status: 'failed', reason: 'sending_paused' },
}

export function emailMetricSendFilters(
    metric: EmailMetricName,
    range: { dateFrom: string; dateTo: string }
): Record<string, string> | null {
    const sends = EMAIL_METRIC_SENDS[metric]
    if (!sends) {
        return null
    }
    const window = logWindow(range)
    return {
        status: sends.status,
        ...(sends.reason ? { reason: sends.reason } : {}),
        date_from: window.dateFrom,
        date_to: window.dateTo,
    }
}

export function openEmailMetricSends(metric: EmailMetricName, range: { dateFrom: string; dateTo: string }): void {
    const filters = emailMetricSendFilters(metric, range)
    if (filters) {
        router.actions.push(router.values.location.pathname, { ...filters, tab: 'sends' }, router.values.hashParams)
    }
}
