import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button,
    Callout,
    CalloutContent,
    CalloutDescription,
    CalloutIcon,
    CalloutTitle,
    Checkbox,
    DatePicker,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldGroup,
    FieldLabel,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Text,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { releaseLaunchLogic } from './releaseLaunchLogic'

export function ReleaseLaunchDialog(): JSX.Element {
    const { launchOpen, launchFlags, launchDate, selectedFlagIds, failedFlags, launchInPast, launching, timezone } =
        useValues(releaseLaunchLogic)
    const { closeLaunch, setLaunchDate, toggleLaunchFlag, launch } = useActions(releaseLaunchLogic)
    const [pickerOpen, setPickerOpen] = useState(false)
    const selected = new Set(selectedFlagIds)

    return (
        <Dialog open={launchOpen} onOpenChange={(open: boolean) => !open && !launching && closeLaunch()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Launch flags on one date</DialogTitle>
                    <DialogDescription>
                        PostHog turns on each selected flag at the same time. The launch shows on the release timeline.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel>Date and time ({timezone})</FieldLabel>
                            <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                                <PopoverTrigger
                                    render={
                                        <Button variant="outline" className="w-fit" data-attr="release-launch-date" />
                                    }
                                >
                                    <IconCalendar />
                                    {launchDate.format('MMM D, YYYY HH:mm')}
                                </PopoverTrigger>
                                <PopoverContent align="start" className="p-0">
                                    <DatePicker
                                        value={launchDate.toDate()}
                                        minDate={new Date()}
                                        maxDate={dayjs().add(1, 'year').toDate()}
                                        showTime
                                        showTimeToggle={false}
                                        onApply={(date) => {
                                            setLaunchDate(dayjs(date))
                                            setPickerOpen(false)
                                        }}
                                        onCancel={() => setPickerOpen(false)}
                                        className="shadow-none ring-0"
                                    />
                                </PopoverContent>
                            </Popover>
                        </Field>
                        <Field>
                            <FieldLabel>Flags to turn on</FieldLabel>
                            <div className="flex flex-col gap-2" data-attr="release-launch-flags">
                                {launchFlags.map((flag) => (
                                    <Checkbox
                                        key={flag.id}
                                        checked={selected.has(flag.id)}
                                        onCheckedChange={(checked: boolean) => toggleLaunchFlag(flag.id, checked)}
                                        data-attr="release-launch-flag"
                                    >
                                        <span className="flex items-center gap-2">
                                            {flag.key}
                                            {flag.active && (
                                                <Text size="xs" variant="muted" render={<span />}>
                                                    Already on
                                                </Text>
                                            )}
                                        </span>
                                    </Checkbox>
                                ))}
                            </div>
                        </Field>
                        {failedFlags.length > 0 && (
                            <Callout tone="destructive" data-attr="release-launch-failed">
                                <CalloutIcon />
                                <CalloutContent>
                                    <CalloutTitle>
                                        These flags could not be scheduled. The other flags are scheduled.
                                    </CalloutTitle>
                                    <ul className="flex flex-col gap-1">
                                        {failedFlags.map((failure) => (
                                            <li key={failure.flagId}>
                                                <CalloutDescription>
                                                    <span className="font-medium">{failure.key}</span>
                                                    {failure.pendingApproval ? (
                                                        <>
                                                            <span>
                                                                : a change to this flag waits for approval. Resolve it
                                                                first, then schedule the launch.{' '}
                                                            </span>
                                                            <LinkPrimitive
                                                                to={urls.featureFlag(failure.flagId)}
                                                                className="underline"
                                                                data-attr="release-launch-failed-open-flag"
                                                            >
                                                                Open the flag
                                                            </LinkPrimitive>
                                                        </>
                                                    ) : (
                                                        <span>: {failure.reason}</span>
                                                    )}
                                                </CalloutDescription>
                                            </li>
                                        ))}
                                    </ul>
                                </CalloutContent>
                            </Callout>
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeLaunch} disabled={launching}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={launch}
                        loading={launching}
                        disabledReason={
                            !selectedFlagIds.length
                                ? 'Select at least one flag'
                                : launchInPast
                                  ? 'Pick a launch time in the future'
                                  : undefined
                        }
                        data-attr="release-launch-confirm"
                    >
                        {selectedFlagIds.length === 1 ? 'Schedule 1 flag' : `Schedule ${selectedFlagIds.length} flags`}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
