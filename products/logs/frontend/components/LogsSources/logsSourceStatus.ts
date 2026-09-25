import type { LemonTagType } from '@posthog/lemon-ui'

import type { LogsSourceHealthStatusEnumApi } from 'products/logs/frontend/generated/api.schemas'

type StatusTag = { label: string; type: LemonTagType }

const STATUS_CONFIG: Record<LogsSourceHealthStatusEnumApi, StatusTag> = {
    receiving: { label: 'Receiving', type: 'success' },
    stale: { label: 'No recent data', type: 'warning' },
    disabled: { label: 'Disabled', type: 'muted' },
    waiting: { label: 'Waiting for first delivery', type: 'default' },
}

const CHECKING: StatusTag = { label: 'Checking', type: 'default' }
const UNAVAILABLE: StatusTag = { label: 'Status unavailable', type: 'muted' }

export function logsSourceStatusTag(
    status: LogsSourceHealthStatusEnumApi | undefined,
    healthUnavailable: boolean
): StatusTag {
    if (status) {
        return STATUS_CONFIG[status]
    }
    return healthUnavailable ? UNAVAILABLE : CHECKING
}
