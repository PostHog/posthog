import { IconClock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export function ReportStartMonitoringPrompt({
    loading,
    onStart,
}: {
    loading: boolean
    onStart: () => void
}): JSX.Element {
    return (
        <div className="@container">
            <div className="flex flex-col gap-2 rounded border bg-surface-secondary px-3 py-2 @[22rem]:flex-row @[22rem]:items-center @[22rem]:justify-between">
                <span className="text-sm text-secondary">Fix already implemented?</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconClock />}
                    loading={loading}
                    onClick={onStart}
                    tooltip="PostHog watches to make sure the fix works"
                    className="self-start @[22rem]:self-auto"
                    data-attr="inbox-report-start-monitoring"
                >
                    Start monitoring now
                </LemonButton>
            </div>
        </div>
    )
}
