import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { MetricChart, MetricChartProps } from './MetricChart'

const LABELS = ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05']
const BREAKDOWN_SERIES = [
    { key: 'organic', label: 'Organic search', data: [48, 64, 52, 76, 60] },
    { key: 'email', label: 'Email newsletter for returning visitors', data: [20, 28, NaN, 30, 36] },
    { key: '', label: 'No channel', data: [0, 12, 8, 16, 20] },
]
const TOTAL_SERIES = [{ key: 'total', label: 'Visitors', data: [68, 104, 60, 122, 116] }]

interface MetricChartPreviewProps {
    state: 'loaded' | 'loading' | 'refreshing' | 'empty' | 'error'
    chartMode: MetricChartProps['chartMode']
    focusedBreakdownValue: string | null
    format: MetricChartProps['format']
    queryId: string | null
    onStateChange: (state: MetricChartPreviewProps['state']) => void
    onChartModeChange: MetricChartProps['onChartModeChange']
    onFocus: MetricChartProps['onFocus']
}

export function MetricChartPreview({
    state,
    chartMode,
    focusedBreakdownValue,
    format,
    queryId,
    onStateChange,
    onChartModeChange,
    onFocus,
}: MetricChartPreviewProps): JSX.Element {
    const series =
        state === 'empty' || state === 'loading' ? [] : chartMode === 'total' ? TOTAL_SERIES : BREAKDOWN_SERIES

    // Pin the scene width so visual snapshots cannot shrink to the controls.
    return (
        <div className="flex w-[60rem] max-w-full flex-col gap-4">
            <MetricChart
                label="Visitors"
                breakdownLabel="Channel"
                format={format}
                timezone="UTC"
                labels={LABELS}
                series={series}
                chartMode={chartMode}
                focusedBreakdownValue={focusedBreakdownValue}
                onChartModeChange={onChartModeChange}
                onFocus={onFocus}
                loading={state === 'loading' || state === 'refreshing'}
                error={
                    state === 'error' && (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Retry', onClick: () => onStateChange('loaded') }}
                        >
                            <span>Couldn't load this chart. Try again.</span>
                            {queryId && (
                                <div className="text-muted text-xs break-all">
                                    <span>Query ID: </span>
                                    <span className="font-mono" translate="no">
                                        {queryId}
                                    </span>
                                </div>
                            )}
                        </LemonBanner>
                    )
                }
            />
            <div className="flex flex-wrap gap-2 items-center">
                <LemonSelect
                    value={state}
                    onChange={onStateChange}
                    options={[
                        { value: 'loaded', label: 'Show data' },
                        { value: 'loading', label: 'Show loading' },
                        { value: 'refreshing', label: 'Show refreshing' },
                        { value: 'empty', label: 'Show empty' },
                        { value: 'error', label: 'Show error' },
                    ]}
                />
                <LemonButton
                    onClick={() => onFocus('')}
                    disabledReason={chartMode === 'total' ? 'Switch to By channel' : undefined}
                >
                    Select no channel
                </LemonButton>
                <span>{`Selected channel: ${focusedBreakdownValue === null ? 'None' : focusedBreakdownValue || 'No channel'}`}</span>
            </div>
        </div>
    )
}
