import type { LemonTagType } from '@posthog/lemon-ui'

import type { LogsSourceHealthStatusEnumApi } from 'products/logs/frontend/generated/api.schemas'

const STATUS_CONFIG: Record<LogsSourceHealthStatusEnumApi, { label: string; type: LemonTagType }> = {
    receiving: { label: 'Receiving', type: 'success' },
    stale: { label: 'No data in the last 2 hours', type: 'warning' },
    disabled: { label: 'Disabled', type: 'muted' },
    waiting: { label: 'Waiting for first delivery', type: 'default' },
}

const CHECKING = { label: 'Checking', type: 'default' } as const

export function logsSourceStatusLabel(status: LogsSourceHealthStatusEnumApi | undefined): string {
    return (status ? STATUS_CONFIG[status] : CHECKING).label
}

export function logsSourceStatusTagType(status: LogsSourceHealthStatusEnumApi | undefined): LemonTagType {
    return (status ? STATUS_CONFIG[status] : CHECKING).type
}
