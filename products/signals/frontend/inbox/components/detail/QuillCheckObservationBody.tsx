import { Text } from '@posthog/quill'

import { humanFriendlyDuration } from 'lib/utils/durations'

import type { CheckObservationContent } from './artefactTypes'
import { describeCheckObservation } from './checkObservationPresentation'

/** The quill sibling of `CheckObservationBody`. */
export function QuillCheckObservationBody({ content }: { content: CheckObservationContent }): JSX.Element {
    const { verdict, explanation, remainingSeconds } = describeCheckObservation(content)

    return (
        <div className="flex w-full flex-col items-start gap-1">
            {verdict ? (
                <>
                    <Text size="xs" render={<span />}>
                        Goal “{content.title}” is <strong>{verdict.matches ? 'on track' : 'not on track'}</strong>.
                    </Text>
                    <Text size="xs" render={<span />}>
                        Measured {verdict.value} against a goal of {verdict.goal}.
                    </Text>
                </>
            ) : (
                <Text size="xs" render={<span />}>
                    {explanation}
                </Text>
            )}
            {remainingSeconds !== null ? (
                <Text size="xs" render={<span />} className="text-subtle-foreground">
                    {humanFriendlyDuration(remainingSeconds, { maxUnits: 2 })} of monitoring remained at this
                    measurement.
                </Text>
            ) : null}
        </div>
    )
}
