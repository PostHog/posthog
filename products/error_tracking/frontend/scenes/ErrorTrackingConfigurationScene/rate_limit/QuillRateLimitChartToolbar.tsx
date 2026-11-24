import { IconRefresh } from '@posthog/icons'
import { Button, Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { RateLimitChartMode } from './rateLimitConfigLogic'
import { formatTotalDuration } from './RateLimitSimulationChart'

const CHART_MODE_OPTIONS: { value: RateLimitChartMode; label: string }[] = [
    { value: 'simulation', label: 'Simulation' },
    { value: 'history', label: 'History' },
]

export function QuillRateLimitChartToolbar({
    chartMode,
    onChartModeChange,
    bucketMinutes,
    loading,
    onRefresh,
}: {
    chartMode: RateLimitChartMode
    onChartModeChange: (mode: RateLimitChartMode) => void
    bucketMinutes: number
    loading: boolean
    onRefresh: () => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <ToggleGroup
                variant="outline"
                aria-label="Chart mode"
                value={[chartMode]}
                onValueChange={(next: string[]) => {
                    const picked = next[0] as RateLimitChartMode | undefined
                    if (picked) {
                        onChartModeChange(picked)
                    }
                }}
            >
                {CHART_MODE_OPTIONS.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value}>
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <div className="flex items-center gap-2">
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    <span>Past&nbsp;</span>
                    <span translate="no">{formatTotalDuration(bucketMinutes)}</span>
                </Text>
                <Button
                    size="icon"
                    aria-label="Refresh with the latest data"
                    tooltip="Refresh with the latest data"
                    onClick={onRefresh}
                    loading={loading}
                >
                    <IconRefresh />
                </Button>
            </div>
        </div>
    )
}
