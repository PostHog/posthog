import { LemonSelectOptions } from '@posthog/lemon-ui'
import { Field, FieldLabel, Text } from '@posthog/quill'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import type { EventsRetentionPeriodSelectProps } from './EventsRetentionPeriodSelect'
import { EventsRetentionSupportPeriod } from './EventsRetentionSupportPeriod'
import { QuillEventsRetentionMonthsSelect } from './QuillEventsRetentionMonthsSelect'
import { retentionPeriodLabel } from './retentionPeriodLabel'

export function QuillEventsRetentionPeriodSelect({
    options,
    supportMonths,
    abovePlan,
    onSelect,
    ...props
}: EventsRetentionPeriodSelectProps & {
    options: LemonSelectOptions<number | null>
    supportMonths: number | null
    abovePlan: boolean
    onSelect: (months: number | null) => void
}): JSX.Element {
    const { retentionMonths, planMonths, level, scope, owner, note, saving, restrictionReason, onSave, dataAttr } =
        props
    const selectId = `${dataAttr}-period`

    return (
        <Field className="max-w-160">
            <FieldLabel htmlFor={supportMonths === null ? selectId : undefined}>Retention period</FieldLabel>
            <div className="flex flex-wrap items-center gap-2">
                {supportMonths === null ? (
                    <QuillEventsRetentionMonthsSelect
                        id={selectId}
                        value={retentionMonths}
                        options={options}
                        onChange={onSelect}
                        loading={saving}
                        disabledReason={restrictionReason}
                        invalid={abovePlan}
                        dataAttr={`${dataAttr}-select`}
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
                    <Text size="xs" variant="destructive" render={<span className="m-0 flex items-center gap-1" />}>
                        <IconErrorOutline className="shrink-0" />
                        <span>{`Your plan's limit is ${retentionPeriodLabel(planMonths)}`}</span>
                    </Text>
                )}
            </div>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                <span>{note}</span>
                {retentionMonths !== null && !abovePlan && (
                    <span> Older events are deleted once a month, so some are kept up to about a month longer.</span>
                )}
            </Text>
        </Field>
    )
}
