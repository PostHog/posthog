import { useState } from 'react'

import { LemonButton, LemonLabel, LemonModal, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { EventsRetentionChangeNote } from './EventsRetentionChangeNote'
import { EventsRetentionLevel } from './eventsRetentionDeletionCountLogic'
import { RetentionPeriods, retentionChangeDeletion } from './retentionChangeDeletion'
import { retentionPeriodLabel } from './retentionPeriodLabel'

export interface EventsRetentionSupportPeriodModalProps {
    periods: RetentionPeriods
    supportMonths: number
    level: EventsRetentionLevel
    owner: string
    scope: string
    options: LemonSelectOptions<number | null>
    onSave: (months: number | null) => void
    onClose: () => void
    dataAttr: string
}

export function EventsRetentionSupportPeriodModal({
    periods,
    supportMonths,
    level,
    owner,
    scope,
    options,
    onSave,
    onClose,
    dataAttr,
}: EventsRetentionSupportPeriodModalProps): JSX.Element {
    const [months, setMonths] = useState<number | null>(null)
    const supportPeriod = retentionPeriodLabel(supportMonths)
    const keptMonths = months ?? periods.defaultMonths
    const deletion = retentionChangeDeletion({ ...periods, retentionMonths: supportMonths }, months)

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title="Change the period PostHog support set?"
            maxWidth="32rem"
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status={deletion ? 'danger' : 'default'}
                        onClick={() => {
                            onSave(months)
                            onClose()
                        }}
                        data-attr={`${dataAttr}-confirm`}
                    >
                        {`Keep events for ${retentionPeriodLabel(keptMonths)}`}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <p className="mb-0">
                    {`PostHog support set ${owner} to keep events for ${supportPeriod}. If you change it, you can only pick one of the standard periods, and you'll need to contact support to get ${supportPeriod} back.`}
                </p>
                <div className="flex flex-col gap-1">
                    <LemonLabel>New retention period</LemonLabel>
                    <LemonSelect<number | null>
                        value={months}
                        onChange={setMonths}
                        options={options}
                        className="w-80 max-w-full"
                        data-attr={`${dataAttr}-support-select`}
                    />
                </div>
                <EventsRetentionChangeNote level={level} months={keptMonths} scope={scope} deletion={deletion} />
            </div>
        </LemonModal>
    )
}
