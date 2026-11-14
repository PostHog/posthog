import { useState } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { retentionPeriodLabel } from 'lib/utils/retentionPeriodLabel'

import {
    EventsRetentionSupportPeriodModal,
    EventsRetentionSupportPeriodModalProps,
} from './EventsRetentionSupportPeriodModal'

export interface EventsRetentionSupportPeriodProps extends Omit<EventsRetentionSupportPeriodModalProps, 'onClose'> {
    saving: boolean
    restrictionReason: string | null
}

export function EventsRetentionSupportPeriod({
    saving,
    restrictionReason,
    ...modalProps
}: EventsRetentionSupportPeriodProps): JSX.Element {
    const [changing, setChanging] = useState(false)

    return (
        <>
            <span className="font-semibold">{retentionPeriodLabel(modalProps.supportMonths)}</span>
            <LemonTag>Set by PostHog support</LemonTag>
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => setChanging(true)}
                loading={saving}
                disabledReason={restrictionReason}
                data-attr={`${modalProps.dataAttr}-change-support-period`}
            >
                Change
            </LemonButton>
            {changing && <EventsRetentionSupportPeriodModal {...modalProps} onClose={() => setChanging(false)} />}
        </>
    )
}
