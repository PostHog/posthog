import { Progress, ProgressLabel, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

/** How far the report is through its observation window. The window has a real start and end, so the bar is measured. */
export function ReportMonitoringWindow({ startedAt, endsAt }: { startedAt: string; endsAt: string }): JSX.Element {
    const start = Date.parse(startedAt)
    const end = Date.parse(endsAt)
    const now = Date.now()
    const ended = now >= end
    const elapsed = end > start ? Math.min(100, Math.max(0, ((now - start) / (end - start)) * 100)) : 100

    return (
        <Progress value={elapsed} variant={ended ? 'success' : 'info'} data-attr="inbox-report-monitoring-window">
            <ProgressLabel>{ended ? 'Monitoring window ended' : 'Monitoring window'}</ProgressLabel>
            <Text
                size="xs"
                variant="muted"
                render={<span />}
                className="ms-auto flex flex-wrap items-center justify-end gap-x-1"
            >
                <span>Started</span>
                <TZLabel time={startedAt} />
                <span aria-hidden>·</span>
                <span>{ended ? 'Ended' : 'Final check'}</span>
                <TZLabel time={endsAt} />
            </Text>
        </Progress>
    )
}
