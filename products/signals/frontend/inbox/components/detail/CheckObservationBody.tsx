import { humanFriendlyDuration } from 'lib/utils/durations'

import type { CheckObservationContent } from './artefactTypes'
import { describeCheckObservation } from './checkObservationPresentation'

export function CheckObservationBody({ content }: { content: CheckObservationContent }): JSX.Element {
    const { verdict, explanation, remainingSeconds } = describeCheckObservation(content)

    return (
        <div className="flex w-full flex-col items-start gap-1 text-xs">
            {verdict ? (
                <>
                    <span>
                        Goal “{content.title}” is <strong>{verdict.matches ? 'on track' : 'not on track'}</strong>.
                    </span>
                    <span>
                        Measured {verdict.value} against a goal of {verdict.goal}.
                    </span>
                </>
            ) : (
                <span>{explanation}</span>
            )}
            {remainingSeconds !== null ? (
                <span className="text-tertiary">
                    {humanFriendlyDuration(remainingSeconds, { maxUnits: 2 })} of monitoring remained at this
                    measurement.
                </span>
            ) : null}
        </div>
    )
}
