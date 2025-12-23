import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { MAX_MULTIPLIER, MIN_MULTIPLIER, errorTrackingSpikeDetectionLogic } from './errorTrackingSpikeDetectionLogic'

export function ErrorTrackingSpikeDetection(): JSX.Element {
    const { multiplier } = useValues(errorTrackingSpikeDetectionLogic)
    const { setMultiplier } = useActions(errorTrackingSpikeDetectionLogic)

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
                    If your issue occurrences increase by {multiplier}x over the baseline, we will emit an internal
                    event <code>issue_spiking</code>
                </div>
            </div>
        </div>
    )
}
