import { TZLabel } from 'lib/components/TZLabel'

/** A message footer's timestamp. The popover waits for a deliberate hover, since the footer sits under the text. */
export function QuillFooterTimestamp({ time }: { time: number }): JSX.Element {
    // A fresh dayjs object every render would defeat TZLabel's memo; a string compares by value.
    return <TZLabel time={new Date(time).toISOString()} hoverOpenDelayMs={500} className="text-xs text-foreground" />
}
