import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { RunActionHistoryDTOApi } from 'products/subscriptions/frontend/generated/api.schemas'

const ADOPTION_STATUS: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'default' }> = {
    pending: { label: 'Decision pending', type: 'warning' },
    adopted: { label: 'Adopted', type: 'success' },
    dismissed: { label: 'Dismissed', type: 'default' },
    abandoned: { label: 'Abandoned', type: 'danger' },
}

const READOUT_STATUS: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'default' }> = {
    waiting: { label: 'Readout not scheduled', type: 'default' },
    scheduled: { label: 'Readout scheduled', type: 'warning' },
    due: { label: 'Readout due', type: 'warning' },
    measuring: { label: 'Measuring', type: 'default' },
    measured: { label: 'Measured', type: 'success' },
    inconclusive: { label: 'Inconclusive', type: 'warning' },
    cancelled: { label: 'Readout cancelled', type: 'default' },
}

export function SubscriptionPulseLifecycleTags({ action }: { action: RunActionHistoryDTOApi }): JSX.Element | null {
    const adoption = action.adoption_status ? ADOPTION_STATUS[action.adoption_status] : null
    const adoptionLabel =
        action.adoption_status === 'pending' && action.artifacts.length > 0 ? 'Adoption pending' : adoption?.label
    const readout = action.readout_status ? READOUT_STATUS[action.readout_status] : null
    if (!adoption && !readout) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-2 text-xs">
            {adoption && adoptionLabel ? <LemonTag type={adoption.type}>{adoptionLabel}</LemonTag> : null}
            {action.adoption_status === 'adopted' && action.adoption_source === 'experiment_launched' ? (
                <LemonTag type="success">Launched</LemonTag>
            ) : null}
            {readout ? <LemonTag type={readout.type}>{readout.label}</LemonTag> : null}
            {action.readout_status === 'scheduled' && action.next_readout_at ? (
                <span className="text-secondary">
                    Scheduled for <TZLabel time={action.next_readout_at} />
                </span>
            ) : null}
        </div>
    )
}
