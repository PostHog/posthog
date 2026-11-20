import { LemonSelectOptions } from '@posthog/lemon-ui'
import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Text,
} from '@posthog/quill'

import { EventsRetentionChangeNote } from './EventsRetentionChangeNote'
import { EventsRetentionLevel } from './eventsRetentionDeletionCountLogic'
import { QuillEventsRetentionMonthsSelect } from './QuillEventsRetentionMonthsSelect'
import { RetentionDeletion } from './retentionChangeDeletion'
import { retentionPeriodLabel } from './retentionPeriodLabel'

export function QuillEventsRetentionSupportPeriodModal({
    months,
    onMonthsChange,
    supportPeriod,
    keptMonths,
    deletion,
    level,
    owner,
    scope,
    options,
    onSave,
    onClose,
    dataAttr,
}: {
    months: number | null
    onMonthsChange: (months: number | null) => void
    supportPeriod: string
    keptMonths: number
    deletion: RetentionDeletion | null
    level: EventsRetentionLevel
    owner: string
    scope: string
    options: LemonSelectOptions<number | null>
    onSave: () => void
    onClose: () => void
    dataAttr: string
}): JSX.Element {
    const selectId = `${dataAttr}-support-period`

    return (
        <Dialog open onOpenChange={(nextOpen: boolean) => !nextOpen && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Change the period PostHog support set?</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Text size="xs" render={<p className="m-0" />}>
                            {`PostHog support set ${owner} to keep events for ${supportPeriod}. If you change it, you can only pick one of the standard periods, and you'll need to contact support to get ${supportPeriod} back.`}
                        </Text>
                        <Field>
                            <FieldLabel htmlFor={selectId}>New retention period</FieldLabel>
                            <QuillEventsRetentionMonthsSelect
                                id={selectId}
                                value={months}
                                options={options}
                                onChange={onMonthsChange}
                                dataAttr={`${dataAttr}-support-select`}
                            />
                        </Field>
                        <Text size="xs" render={<div className="m-0" />}>
                            <EventsRetentionChangeNote
                                level={level}
                                months={keptMonths}
                                scope={scope}
                                deletion={deletion}
                            />
                        </Text>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                    <Button
                        variant={deletion ? 'destructive' : 'primary'}
                        onClick={onSave}
                        data-attr={`${dataAttr}-confirm`}
                    >
                        {`Keep events for ${retentionPeriodLabel(keptMonths)}`}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
