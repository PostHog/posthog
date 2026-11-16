import { useState } from 'react'

import { LemonButton, LemonDialog, LemonLabel, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { EventsRetentionChangeNote } from './EventsRetentionChangeNote'
import { EventsRetentionLevel } from './eventsRetentionDeletionCountLogic'
import { EventsRetentionPeriodChoices, eventsRetentionPeriodOptions } from './eventsRetentionPeriodOptions'
import { EventsRetentionSupportPeriodModal } from './EventsRetentionSupportPeriodModal'
import { RetentionPeriods, retentionChangeDeletion } from './retentionChangeDeletion'
import { retentionPeriodLabel } from './retentionPeriodLabel'

export interface EventsRetentionPeriodSelectProps extends RetentionPeriods, EventsRetentionPeriodChoices {
    level: EventsRetentionLevel
    scope: string
    owner: string
    note: string | JSX.Element
    saving: boolean
    restrictionReason: string | null
    onSave: (months: number | null) => void
}

export function EventsRetentionPeriodSelect(props: EventsRetentionPeriodSelectProps): JSX.Element {
    const {
        retentionMonths,
        defaultMonths,
        choices,
        level,
        scope,
        owner,
        note,
        saving,
        restrictionReason,
        onSave,
        dataAttr,
    } = props
    const [changingSupportPeriod, setChangingSupportPeriod] = useState(false)
    const options = eventsRetentionPeriodOptions(props)
    const supportMonths = retentionMonths !== null && !choices.includes(retentionMonths) ? retentionMonths : null

    const confirm = (months: number | null): void => {
        const period = retentionPeriodLabel(months ?? defaultMonths)
        const deletion = retentionChangeDeletion(props, months)
        LemonDialog.open({
            title: `Keep events for ${period}?`,
            maxWidth: '32rem',
            content: (
                <EventsRetentionChangeNote
                    level={level}
                    months={months ?? defaultMonths}
                    scope={scope}
                    deletion={deletion}
                />
            ),
            primaryButton: {
                children: `Keep events for ${period}`,
                status: deletion ? 'danger' : 'default',
                onClick: () => onSave(months),
                'data-attr': `${dataAttr}-confirm`,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex flex-col gap-1 max-w-160">
            <LemonLabel>Retention period</LemonLabel>
            {supportMonths === null ? (
                <LemonSelect<number | null>
                    value={retentionMonths}
                    onChange={confirm}
                    options={options}
                    loading={saving}
                    disabledReason={restrictionReason ?? undefined}
                    className="w-80 max-w-full"
                    data-attr={`${dataAttr}-select`}
                />
            ) : (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{retentionPeriodLabel(supportMonths)}</span>
                    <LemonTag>Set by PostHog support</LemonTag>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => setChangingSupportPeriod(true)}
                        loading={saving}
                        disabledReason={restrictionReason}
                        data-attr={`${dataAttr}-change-support-period`}
                    >
                        Change
                    </LemonButton>
                </div>
            )}
            <p className="mb-0 text-xs text-secondary">
                <span>{note}</span>
                {retentionMonths !== null && (
                    <span> Older events are deleted once a month, so some are kept up to about a month longer.</span>
                )}
            </p>
            {supportMonths !== null && changingSupportPeriod && (
                <EventsRetentionSupportPeriodModal
                    periods={props}
                    supportMonths={supportMonths}
                    level={level}
                    owner={owner}
                    scope={scope}
                    options={options}
                    onSave={onSave}
                    onClose={() => setChangingSupportPeriod(false)}
                    dataAttr={dataAttr}
                />
            )}
        </div>
    )
}
