import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { errorTrackingSpikeDetectionLogic } from './errorTrackingSpikeDetectionLogic'

function HighlightedValue({ children }: { children: React.ReactNode }): JSX.Element {
    return <span className="font-semibold text-primary whitespace-nowrap">{children}</span>
}

export function ErrorTrackingSpikeDetection(): JSX.Element {
    const { multiplier, multiplierConfig } = useValues(errorTrackingSpikeDetectionLogic)
    const { setMultiplier } = useActions(errorTrackingSpikeDetectionLogic)

    return (
        <div className="flex flex-col gap-y-4">
            <div>
                <h3>Spike detection</h3>
                <p className="text-muted">
                    Configure when PostHog should consider an issue to be "spiking", based on a sudden increase in
                    occurrences.
                </p>
            </div>

            <div className="flex flex-col gap-4">
                <div className="min-w-44 max-w-60">
                    <div className="text-sm text-muted mb-1">Multiplier</div>
                    <LemonInput
                        type="number"
                        min={multiplierConfig.min}
                        max={multiplierConfig.max}
                        value={multiplier}
                        suffix="x"
                        onChange={(value) => {
                            setMultiplier(Number(value))
                        }}
                    />
                </div>
            </div>

            <div className="bg-bg-light border border-border rounded-lg p-4">
                <div className="text-sm">
                    If your issue occurrences increase by <HighlightedValue>{multiplier}x</HighlightedValue> over{' '}
                    <HighlightedValue>1 hour</HighlightedValue>, we will emit an internal event{' '}
                    <code>issue_spiking</code> to which you can subscribe in the alerts table in the Alerting tab.
                </div>
            </div>
        </div>
    )
}
