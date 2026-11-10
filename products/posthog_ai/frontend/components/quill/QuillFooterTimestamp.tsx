import { TZLabel } from 'lib/components/TZLabel'

export function QuillFooterTimestamp({ time }: { time: number }): JSX.Element {
    // A fresh dayjs object every render would defeat TZLabel's memo; a string compares by value.
    return <TZLabel time={new Date(time).toISOString()} hoverOpenDelayMs={500} className="text-xs text-foreground" />
}
