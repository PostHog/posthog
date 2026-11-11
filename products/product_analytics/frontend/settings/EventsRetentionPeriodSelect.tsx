import { LemonDialog, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import { EventsRetentionChangeNote } from './EventsRetentionChangeNote'
import { EventsRetentionLevel } from './eventsRetentionDeletionCountLogic'
import { EventsRetentionPeriodChoices, eventsRetentionPeriodOptions } from './eventsRetentionPeriodOptions'
import { EventsRetentionSupportPeriod } from './EventsRetentionSupportPeriod'
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
        planMonths,
        level,
        scope,
        owner,
        note,
        saving,
        restrictionReason,
        onSave,
        dataAttr,
    } = props
    const options = eventsRetentionPeriodOptions(props)
    const supportMonths = retentionMonths !== null && !choices.includes(retentionMonths) ? retentionMonths : null
    const abovePlan = retentionMonths !== null && retentionMonths > planMonths

    const confirm = (months: number | null): void => {
        const keptMonths = months ?? defaultMonths
        const period = retentionPeriodLabel(keptMonths)
        const deletion = retentionChangeDeletion(props, months)
        LemonDialog.open({
            title: `Keep events for ${period}?`,
            maxWidth: '32rem',
            content: <EventsRetentionChangeNote level={level} months={keptMonths} scope={scope} deletion={deletion} />,
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
            <div className="flex flex-wrap items-center gap-2">
                {supportMonths === null ? (
                    <LemonSelect<number | null>
                        value={retentionMonths}
                        onChange={confirm}
                        options={options}
                        loading={saving}
                        disabledReason={restrictionReason}
                        status={abovePlan ? 'danger' : 'default'}
                        className="w-80 max-w-full"
                        data-attr={`${dataAttr}-select`}
                    />
                ) : (
                    <EventsRetentionSupportPeriod
                        periods={props}
                        supportMonths={supportMonths}
                        level={level}
                        owner={owner}
                        scope={scope}
                        options={options}
                        onSave={onSave}
                        saving={saving}
                        restrictionReason={restrictionReason}
                        dataAttr={dataAttr}
                    />
                )}
                {abovePlan && (
                    <span className="flex items-center gap-1 text-sm text-danger">
                        <IconErrorOutline className="shrink-0 text-xl" />
                        {`Your plan's limit is ${retentionPeriodLabel(planMonths)}`}
                    </span>
                )}
            </div>
            <p className="mb-0 text-xs text-secondary">
                <span>{note}</span>
                {retentionMonths !== null && !abovePlan && (
                    <span> Older events are deleted once a month, so some are kept up to about a month longer.</span>
                )}
            </p>
        </div>
    )
}
