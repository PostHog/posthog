import { useState } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import {
    EventsRetentionSupportPeriodModal,
    EventsRetentionSupportPeriodModalProps,
} from './EventsRetentionSupportPeriodModal'
import { QuillEventsRetentionSupportPeriod } from './QuillEventsRetentionSupportPeriod'
import { retentionPeriodLabel } from './retentionPeriodLabel'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillEventsRetentionSupportPeriod
                saving={saving}
                restrictionReason={restrictionReason}
                changing={changing}
                onChangingChange={setChanging}
                {...modalProps}
            />
        )
    }

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
