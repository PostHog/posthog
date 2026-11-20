import { TZLabel } from 'lib/components/TZLabel'

export function MonitoringTime({ iso }: { iso: string }): JSX.Element {
    return <TZLabel time={iso} formatDate="MMM D" formatTime="h:mm A" />
}
