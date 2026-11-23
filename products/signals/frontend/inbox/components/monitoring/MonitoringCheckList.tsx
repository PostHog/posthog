import { IconGraph, IconSparkles } from '@posthog/icons'
import { LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import type {
    MonitoringCheckStateEnumApi,
    MonitoringCheckSummaryApi,
} from 'products/signals/frontend/generated/api.schemas'

const CHECK_STATE_TAG: Record<MonitoringCheckStateEnumApi, { label: string; type: LemonTagType }> = {
    passed: { label: 'Passed', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
    cancelled: { label: 'Cancelled', type: 'muted' },
    on_track: { label: 'On track', type: 'success' },
    not_on_track: { label: 'Not on track', type: 'warning' },
    awaiting_reading: { label: 'No reading yet', type: 'muted' },
    readings_hidden: { label: 'Readings hidden', type: 'muted' },
    final_check_only: { label: 'Checked at window end', type: 'default' },
}

export function MonitoringCheckList({ checks }: { checks: readonly MonitoringCheckSummaryApi[] }): JSX.Element | null {
    if (!checks.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-1.5">
            <div className="text-xs font-semibold text-secondary">
                {checks.length === 1 ? 'Check' : `${checks.length} checks`}
            </div>
            {checks.map((check) => (
                <div key={check.check_id} className="flex items-start gap-1.5 text-xs">
                    {check.kind === 'metric_threshold' ? (
                        <IconGraph className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
                    ) : (
                        <IconSparkles className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
                    )}
                    <span className="min-w-0 flex-1">{check.title}</span>
                    <LemonTag size="small" type={CHECK_STATE_TAG[check.state].type} className="shrink-0">
                        {CHECK_STATE_TAG[check.state].label}
                    </LemonTag>
                </div>
            ))}
        </div>
    )
}
