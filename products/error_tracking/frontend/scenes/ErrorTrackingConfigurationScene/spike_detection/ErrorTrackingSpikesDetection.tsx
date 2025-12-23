import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { MAX_MULTIPLIER, MIN_MULTIPLIER, errorTrackingSpikesDetectionLogic } from './errorTrackingSpikesDetectionLogic'

export function ErrorTrackingSpikesDetection(): JSX.Element {
    const { multiplier } = useValues(errorTrackingSpikesDetectionLogic)
    const { setMultiplier } = useActions(errorTrackingSpikesDetectionLogic)

    return (
        <div className="flex flex-col gap-y-2">
            <p>
                Configure when PostHog should consider an issue to be "spiking", based on a sudden increase in
                occurrences.
            </p>

            <div className="flex flex-col gap-4">
                <div className="min-w-44 max-w-60">
                    <div className="text-sm text-muted mb-1">Multiplier</div>
                    <LemonInput
                        type="number"
                        min={MIN_MULTIPLIER}
                        max={MAX_MULTIPLIER}
                        value={multiplier}
                        onChange={(value) => {
                            setMultiplier(Number(value))
                        }}
                    />
                </div>
            </div>

            <div className="bg-bg-light border border-border rounded-lg p-4">
                <div className="text-sm">
                    If the number of occurrences of your issue increases by{' '}
                    <span className="font-semibold bg-warning-highlight text-warning-dark px-1.5 py-0.5 rounded">
                        {multiplier}x
                    </span>{' '}
                    compared to the baseline, we will emit an internal event <code>issue_spiking</code>
                </div>
            </div>
            <div className="bg-bg-light border border-border rounded-lg p-4">
                <div className="text-sm">
                    Baseline is calculated as the average number of occurences over the last hour
                </div>
            </div>
        </div>
    )
}
